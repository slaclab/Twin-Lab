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

from .collision import CollisionModel
from .paths import EXPORT_ROOT, resolve_repo_path, review_artifact_stem

WARN_LABEL = "Clearance warning band (mm)"
CLEAR_RGB = [0.13, 0.42, 0.18]
INTERFERENCE_RGB = [0.60, 0.08, 0.08]


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
        home = self.logical_offset * self.scale
        return lower, upper, home


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
            )
            for row in csv.DictReader(stream)
        ]


def run_collision_viewer(
    package_dir: str | Path,
    *,
    warn_mm: float = 5.0,
    ignore_file: str | Path | None = None,
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
    model = CollisionModel(scene, _read_ignored(ignore_file))
    print(
        f"Loaded {_proximity_geometry_count(model)} collision geometries "
        f"in {time.monotonic() - load_start:.0f} s"
    )

    for joint in joints:
        lower, upper, home = joint.slider_bounds()
        meshcat.AddSlider(joint.label, lower, upper, 0.05, home)
    meshcat.AddSlider(WARN_LABEL, 0.0, 50.0, 0.5, warn_mm)
    meshcat.AddButton("Reset to home")
    meshcat.AddButton("Log clearance report")
    meshcat.AddButton("Stop viewer", "Escape")

    print(f"{len(joints)} joints")
    print("Background is GREEN when clear and RED when any pair is touching.")
    print("Press Escape in Meshcat or Ctrl-C here to stop.")

    reset_clicks = 0
    log_clicks = 0
    previous_pose: tuple[list[float], float] | None = None
    previous_interference: bool | None = None
    previous_summary = ""
    while meshcat.GetButtonClicks("Stop viewer") == 0:
        new_reset = meshcat.GetButtonClicks("Reset to home")
        if new_reset != reset_clicks:
            reset_clicks = new_reset
            for joint in joints:
                meshcat.SetSliderValue(joint.label, joint.slider_bounds()[2])

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
            report = model.report(warn_m=warn_m)
            if report.interference != previous_interference:
                previous_interference = report.interference
                _set_status(meshcat, report.interference)
            if new_log != log_clicks:
                log_clicks = new_log
                _print_report(report)
            elif report.summary() != previous_summary:
                previous_summary = report.summary()
                print(report.summary())
        time.sleep(0.1)


def _set_status(meshcat, interfering: bool) -> None:
    """Paint the whole viewport red for interference or green for clearance."""

    color = INTERFERENCE_RGB if interfering else CLEAR_RGB
    meshcat.SetProperty("/Background", "top_color", color)
    meshcat.SetProperty("/Background", "bottom_color", color)
    print("INTERFERENCE" if interfering else "CLEAR")


def _read_ignored(ignore_file: str | Path | None) -> frozenset[tuple[str, str]]:
    if ignore_file is None:
        return frozenset()
    from .collision import read_ignored_pairs

    return read_ignored_pairs(ignore_file)


def _needs_recompile(package_dir: Path) -> bool:
    """Rebuild packages predating the OBJ-visual fix; Meshcat silently skips STL visuals."""

    if not (package_dir / "joint_metadata.csv").exists():
        return True
    sdf_path = next(
        (path for path in sorted(package_dir.glob("*.sdf")) if not path.stem.endswith("_matlab")),
        None,
    )
    return sdf_path is None or ".stl</uri>" in sdf_path.read_text(encoding="utf-8")


def _proximity_geometry_count(model: CollisionModel) -> int:
    from pydrake.geometry import Role

    scene_context = model.scene.scene_graph.GetMyContextFromRoot(model.context)
    query = model.scene.scene_graph.get_query_output_port().Eval(scene_context)
    return query.inspector().NumGeometriesWithRole(Role.kProximity)


def _print_report(report) -> None:
    print(f"\n--- clearance report ({report.warn_m * 1000:.1f} mm band) ---")
    if not report.clearances:
        print("  nothing within the warning band")
    for item in report.clearances[:25]:
        state = "TOUCH" if item.distance_m <= 0.0 else "close"
        first, second = item.names
        print(f"  {state} {item.distance_m * 1000:+8.2f} mm  {first}  <->  {second}")
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
        )
    except KeyboardInterrupt:
        print("\nCollision viewer stopped.")


if __name__ == "__main__":
    main()
