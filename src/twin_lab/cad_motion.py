"""Provisional rigid-group motion viewer for STEP-derived CAD geometry."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .cad_geometry import leaf_occurrences, occurrence_center_m, write_group_obj
from .constraints_wizard import _read_step_document, check_kinematics_review
from .paths import CACHE_ROOT, resolve_repo_path, review_artifact_stem


@dataclass(frozen=True)
class MotionJoint:
    name: str
    parent_group: str
    child_group: str
    axis_xyz: tuple[float, float, float]
    limits_m: tuple[float, float]
    home_m: float


@dataclass(frozen=True)
class MotionSetup:
    review_path: Path
    groups: dict[str, tuple[str, ...]]
    joints: tuple[MotionJoint, ...]
    meshes: dict[str, Path]
    model_origin_ref: str | None
    model_origin_m: tuple[float, float, float]


def prepare_motion_setup(
    review_path: str | Path,
    *,
    linear_deflection_mm: float = 0.5,
) -> MotionSetup:
    """Export one assembled OBJ mesh per reviewed rigid group."""

    review_file = resolve_repo_path(review_path).resolve()
    review = yaml.safe_load(review_file.read_text(encoding="utf-8"))
    status = check_kinematics_review(review_file)
    problems = status["unknown"] + status["duplicate"] + status["joint_errors"]
    if problems:
        raise ValueError("Kinematics review contains errors; run slac-cad-manifest --check")
    if status["unassigned"]:
        raise ValueError("Kinematics review has unassigned parts; run slac-cad-manifest --check")

    manifest = yaml.safe_load(Path(status["manifest"]).read_text(encoding="utf-8"))
    source_step = resolve_repo_path(
        manifest["source_step"], relative_to=Path(status["manifest"]).parent
    )

    groups = {
        str(name): tuple(str(ref) for ref in value.get("occurrences", []))
        for name, value in review["rigid_groups"].items()
    }
    joints = tuple(_parse_joint(item) for item in review["joints"])

    document, _, roots = _read_step_document(source_step)
    assert document is not None  # Keep XCAF labels alive during mesh export.
    occurrences = leaf_occurrences(roots)
    missing = sorted({ref for refs in groups.values() for ref in refs} - set(occurrences))
    if missing:
        raise ValueError(f"STEP traversal did not find reviewed parts: {', '.join(missing)}")

    model_origin_ref = review.get("model_origin_ref")
    if model_origin_ref is not None:
        model_origin_ref = str(model_origin_ref)
        if model_origin_ref not in occurrences:
            raise ValueError(f"model_origin_ref does not identify a STEP leaf: {model_origin_ref}")
        model_origin_m = occurrence_center_m(occurrences[model_origin_ref])
    else:
        model_origin_m = (0.0, 0.0, 0.0)

    output_dir = CACHE_ROOT / "motion" / review_artifact_stem(review_file)
    output_dir.mkdir(parents=True, exist_ok=True)
    meshes: dict[str, Path] = {}
    for group_name, references in groups.items():
        output = output_dir / f"{group_name}.obj"
        write_group_obj(
            [occurrences[reference] for reference in references],
            output,
            linear_deflection_mm=linear_deflection_mm,
            model_origin_m=model_origin_m,
        )
        meshes[group_name] = output

    return MotionSetup(
        review_path=review_file,
        groups=groups,
        joints=joints,
        meshes=meshes,
        model_origin_ref=model_origin_ref,
        model_origin_m=model_origin_m,
    )


def run_motion_viewer(setup: MotionSetup) -> None:
    """Show reviewed CAD groups with nested prismatic motion sliders."""

    from pydrake.geometry import Mesh, Meshcat, Rgba
    from pydrake.math import RigidTransform

    meshcat = Meshcat()
    group_paths = _group_paths(setup)
    colors = [
        Rgba(0.55, 0.58, 0.62, 1.0),
        Rgba(0.20, 0.48, 0.90, 1.0),
        Rgba(0.25, 0.75, 0.40, 1.0),
        Rgba(0.95, 0.55, 0.12, 1.0),
    ]
    for index, (group_name, mesh_path) in enumerate(setup.meshes.items()):
        meshcat.SetObject(
            f"{group_paths[group_name]}/geometry",
            Mesh(mesh_path, 1.0),
            colors[index % len(colors)],
        )

    for joint in setup.joints:
        meshcat.AddSlider(
            f"{joint.name} (mm)",
            joint.limits_m[0] * 1000.0,
            joint.limits_m[1] * 1000.0,
            0.1,
            joint.home_m * 1000.0,
        )
    meshcat.AddButton("Reset to home")
    meshcat.AddButton("Stop viewer", "Escape")
    # pydrake's stub gives SetCameraPose a malformed Eigen shape; lists convert at runtime.
    meshcat.SetCameraPose([0.4, 0.4, 0.4], [0.0, 0.0, 0.0])  # pyright: ignore[reportArgumentType]

    print("PROVISIONAL MOTION MODEL — do not use for hardware limits")
    print(f"Motion viewer: {meshcat.web_url()}")
    print("Use the x/y/z sliders in the Controls panel; press Escape to stop.")

    reset_clicks = 0
    while meshcat.GetButtonClicks("Stop viewer") == 0:
        new_reset_clicks = meshcat.GetButtonClicks("Reset to home")
        if new_reset_clicks != reset_clicks:
            reset_clicks = new_reset_clicks
            for joint in setup.joints:
                meshcat.SetSliderValue(f"{joint.name} (mm)", joint.home_m * 1000.0)

        for joint in setup.joints:
            value_m = meshcat.GetSliderValue(f"{joint.name} (mm)") / 1000.0
            translation = [component * value_m for component in joint.axis_xyz]
            meshcat.SetTransform(group_paths[joint.child_group], RigidTransform(translation))
        time.sleep(0.05)


def _parse_joint(value: dict[str, Any]) -> MotionJoint:
    axis = tuple(float(item) for item in value["axis_xyz"])
    norm = math.sqrt(sum(item * item for item in axis))
    if norm == 0.0:
        raise ValueError(f"Joint '{value['name']}' has a zero axis")
    limits = tuple(float(item) for item in value["limits"])
    return MotionJoint(
        name=str(value["name"]),
        parent_group=str(value["parent_group"]),
        child_group=str(value["child_group"]),
        axis_xyz=tuple(item / norm for item in axis),
        limits_m=(limits[0], limits[1]),
        home_m=float(value["home"]),
    )


def _group_paths(setup: MotionSetup) -> dict[str, str]:
    parents = {joint.child_group: joint.parent_group for joint in setup.joints}

    def path_for(group: str, active: set[str] | None = None) -> str:
        active = set() if active is None else active
        if group in active:
            raise ValueError(f"Cycle in rigid-group hierarchy at '{group}'")
        parent = parents.get(group)
        if parent is None:
            return f"/CAD/{group}"
        return f"{path_for(parent, active | {group})}/{group}"

    return {group: path_for(group) for group in setup.groups}


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Move reviewed STEP rigid groups in Meshcat")
    parser.add_argument("kinematics_review")
    parser.add_argument(
        "--mesh-only",
        action="store_true",
        help="Generate the rigid-group OBJ files without starting Meshcat",
    )
    args = parser.parse_args()

    setup = prepare_motion_setup(args.kinematics_review)
    print("Generated rigid-group meshes:")
    for group, path in setup.meshes.items():
        print(f"  {group}: {path}")
    if setup.model_origin_ref is not None:
        print(f"Display origin: center of {setup.model_origin_ref} (provisional)")
    if not args.mesh_only:
        try:
            run_motion_viewer(setup)
        except KeyboardInterrupt:
            print("\nMotion viewer stopped.")


if __name__ == "__main__":
    main()
