"""Provisional rigid-group motion viewer for STEP-derived CAD geometry."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from OCP.Bnd import Bnd_Box
from OCP.BRep import BRep_Tool
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS
from OCP.XCAFDoc import XCAFDoc_ShapeTool

from .constraints_wizard import _read_step_document, check_kinematics_review


@dataclass(frozen=True)
class OccurrenceShape:
    """A STEP leaf shape and its assembled location."""

    ref: str
    name: str
    label: Any
    global_location: Any


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

    review_file = Path(review_path)
    review = yaml.safe_load(review_file.read_text(encoding="utf-8"))
    status = check_kinematics_review(review_file)
    problems = status["unknown"] + status["duplicate"] + status["joint_errors"]
    if problems:
        raise ValueError("Kinematics review contains errors; run slac-cad-manifest --check")
    if status["unassigned"]:
        raise ValueError("Kinematics review has unassigned parts; run slac-cad-manifest --check")

    manifest = yaml.safe_load(Path(status["manifest"]).read_text(encoding="utf-8"))
    source_step = Path(manifest["source_step"])
    if not source_step.is_absolute() and not source_step.exists():
        source_step = Path(status["manifest"]).parent / source_step

    groups = {
        str(name): tuple(str(ref) for ref in value.get("occurrences", []))
        for name, value in review["rigid_groups"].items()
    }
    joints = tuple(_parse_joint(item) for item in review["joints"])

    document, _, roots = _read_step_document(source_step)
    assert document is not None  # Keep XCAF labels alive during mesh export.
    occurrences = _leaf_occurrences(roots)
    missing = sorted({ref for refs in groups.values() for ref in refs} - set(occurrences))
    if missing:
        raise ValueError(f"STEP traversal did not find reviewed parts: {', '.join(missing)}")

    model_origin_ref = review.get("model_origin_ref")
    if model_origin_ref is not None:
        model_origin_ref = str(model_origin_ref)
        if model_origin_ref not in occurrences:
            raise ValueError(f"model_origin_ref does not identify a STEP leaf: {model_origin_ref}")
        model_origin_m = _occurrence_center_m(occurrences[model_origin_ref])
    else:
        model_origin_m = (0.0, 0.0, 0.0)

    output_dir = source_step.with_suffix(".motion")
    output_dir.mkdir(exist_ok=True)
    meshes: dict[str, Path] = {}
    for group_name, references in groups.items():
        output = output_dir / f"{group_name}.obj"
        _write_group_obj(
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
    meshcat.SetCameraPose([0.4, 0.4, 0.4], [0.0, 0.0, 0.0])

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


def _leaf_occurrences(roots: Any) -> dict[str, OccurrenceShape]:
    result: dict[str, OccurrenceShape] = {}
    counters = {"assembly": 0, "part": 0}
    identity = TopLoc_Location()

    def walk(label: Any, parent_location: Any, *, is_root: bool = False) -> None:
        target = label if is_root else _referred_or_self(label)
        is_assembly = bool(XCAFDoc_ShapeTool.IsAssembly_s(target))
        key = "assembly" if is_assembly else "part"
        counters[key] += 1
        ref = f"{'A' if is_assembly else 'P'}{counters[key]:03d}"
        local = TopLoc_Location() if is_root else XCAFDoc_ShapeTool.GetLocation_s(label)
        global_location = parent_location.Multiplied(local)

        if is_assembly:
            children = _components(target)
            for index in range(1, children.Length() + 1):
                walk(children.Value(index), global_location)
        else:
            result[ref] = OccurrenceShape(
                ref=ref,
                name=ref,
                label=target,
                global_location=global_location,
            )

    for index in range(1, roots.Length() + 1):
        walk(roots.Value(index), identity, is_root=True)
    return result


def _components(label: Any) -> Any:
    from OCP.TDF import TDF_LabelSequence

    children = TDF_LabelSequence()
    XCAFDoc_ShapeTool.GetComponents_s(label, children)
    return children


def _referred_or_self(label: Any) -> Any:
    from OCP.TDF import TDF_Label

    referred = TDF_Label()
    return referred if XCAFDoc_ShapeTool.GetReferredShape_s(label, referred) else label


def _write_group_obj(
    occurrences: list[OccurrenceShape],
    output: Path,
    *,
    linear_deflection_mm: float,
    model_origin_m: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> None:
    vertices: list[tuple[float, float, float]] = []
    triangles: list[tuple[int, int, int]] = []

    for occurrence in occurrences:
        placed = _placed_shape(occurrence)
        BRepMesh_IncrementalMesh(placed, linear_deflection_mm, False, 0.5, True).Perform()

        explorer = TopExp_Explorer(placed, TopAbs_FACE)
        while explorer.More():
            face = TopoDS.Face_s(explorer.Current())
            face_location = TopLoc_Location()
            triangulation = BRep_Tool.Triangulation_s(face, face_location)
            if triangulation is not None:
                offset = len(vertices)
                transform = face_location.Transformation()
                for index in range(1, triangulation.NbNodes() + 1):
                    point = triangulation.Node(index).Transformed(transform)
                    vertices.append(
                        (
                            point.X() * 0.001 - model_origin_m[0],
                            point.Y() * 0.001 - model_origin_m[1],
                            point.Z() * 0.001 - model_origin_m[2],
                        )
                    )
                for index in range(1, triangulation.NbTriangles() + 1):
                    triangle = triangulation.Triangle(index)
                    n1, n2, n3 = (triangle.Value(i) for i in (1, 2, 3))
                    if face.Orientation() == TopAbs_REVERSED:
                        n1, n2, n3 = n3, n2, n1
                    triangles.append((offset + n1, offset + n2, offset + n3))
            explorer.Next()

    if not vertices or not triangles:
        raise ValueError(f"Rigid group produced no mesh triangles: {output.stem}")
    lines = [f"v {x:.9g} {y:.9g} {z:.9g}" for x, y, z in vertices]
    lines.extend(f"f {a} {b} {c}" for a, b, c in triangles)
    output.write_text("\n".join(lines) + "\n", encoding="ascii")


def _placed_shape(occurrence: OccurrenceShape) -> Any:
    shape = XCAFDoc_ShapeTool.GetShape_s(occurrence.label)
    return BRepBuilderAPI_Transform(
        shape,
        occurrence.global_location.Transformation(),
        True,
    ).Shape()


def _occurrence_center_m(occurrence: OccurrenceShape) -> tuple[float, float, float]:
    """Return the assembled bounding-box center for a provisional display datum."""

    bounds = Bnd_Box()
    BRepBndLib.Add_s(_placed_shape(occurrence), bounds, False)
    x_min, y_min, z_min, x_max, y_max, z_max = bounds.Get()
    return (
        (x_min + x_max) * 0.0005,
        (y_min + y_max) * 0.0005,
        (z_min + z_max) * 0.0005,
    )


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
