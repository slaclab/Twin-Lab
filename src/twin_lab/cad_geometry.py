"""Shared Open Cascade traversal and mesh-export helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


@dataclass(frozen=True)
class OccurrenceShape:
    """A STEP leaf shape and its assembled location."""

    ref: str
    name: str
    label: Any
    global_location: Any


def leaf_occurrences(roots: Any) -> dict[str, OccurrenceShape]:
    """Return stable short references for every leaf in an XCAF assembly."""

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
            result[ref] = OccurrenceShape(ref, ref, target, global_location)

    for index in range(1, roots.Length() + 1):
        walk(roots.Value(index), identity, is_root=True)
    return result


def write_group_obj(
    occurrences: list[OccurrenceShape],
    output: Path,
    *,
    linear_deflection_mm: float,
    model_origin_m: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> None:
    """Write globally positioned occurrences as one OBJ with per-part object boundaries."""

    vertices: list[tuple[float, float, float]] = []
    grouped_triangles: list[tuple[str, list[tuple[int, int, int]]]] = []

    for occurrence in occurrences:
        triangles: list[tuple[int, int, int]] = []
        placed = placed_shape(occurrence)
        BRepMesh_IncrementalMesh(placed, linear_deflection_mm, False, 0.5, True).Perform()
        explorer = TopExp_Explorer(placed, TopAbs_FACE)
        while explorer.More():
            # OCP's stub omits the bare TopoDS class; Face_s exists at runtime.
            face = TopoDS.Face_s(explorer.Current())  # pyright: ignore[reportAttributeAccessIssue]
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
        if triangles:
            grouped_triangles.append((occurrence.ref, triangles))

    if not vertices or not grouped_triangles:
        raise ValueError(f"Rigid group produced no mesh triangles: {output.stem}")
    lines = [f"v {x:.9g} {y:.9g} {z:.9g}" for x, y, z in vertices]
    for reference, triangles in grouped_triangles:
        lines.append(f"o {reference}")
        lines.extend(f"f {a} {b} {c}" for a, b, c in triangles)
    output.write_text("\n".join(lines) + "\n", encoding="ascii")


def placed_shape(occurrence: OccurrenceShape) -> Any:
    """Return a copied shape transformed into the assembled coordinate frame."""

    shape = XCAFDoc_ShapeTool.GetShape_s(occurrence.label)
    return BRepBuilderAPI_Transform(
        shape,
        occurrence.global_location.Transformation(),
        True,
    ).Shape()


def occurrence_center_m(occurrence: OccurrenceShape) -> tuple[float, float, float]:
    """Return the assembled bounding-box center in metres."""

    bounds = Bnd_Box()
    BRepBndLib.Add_s(placed_shape(occurrence), bounds, False)
    x_min, y_min, z_min, x_max, y_max, z_max = bounds.Get()
    return (
        (x_min + x_max) * 0.0005,
        (y_min + y_max) * 0.0005,
        (z_min + z_max) * 0.0005,
    )


def _components(label: Any) -> Any:
    from OCP.TDF import TDF_LabelSequence

    children = TDF_LabelSequence()
    XCAFDoc_ShapeTool.GetComponents_s(label, children)
    return children


def _referred_or_self(label: Any) -> Any:
    from OCP.TDF import TDF_Label

    referred = TDF_Label()
    return referred if XCAFDoc_ShapeTool.GetReferredShape_s(label, referred) else label
