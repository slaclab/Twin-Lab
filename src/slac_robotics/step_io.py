"""STEP import and mesh interference helpers.

This module enables a practical CAD-based collision path:
1) Read STEP geometry via OpenCascade (OCP).
2) Tessellate to triangle meshes.
3) Run mesh-mesh collision checks with trimesh + python-fcl.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import trimesh
from trimesh.collision import CollisionManager

from OCP.BRep import BRep_Tool
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_Reader
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS


_SUPPORTED_STEP_SUFFIXES = {".stp", ".step"}


def _ensure_supported_step_path(path: Path) -> None:
    suffix = path.suffix.lower()
    if suffix in _SUPPORTED_STEP_SUFFIXES:
        return

    raise ValueError(
        "Unsupported CAD format. This importer currently supports STEP only "
        f"({sorted(_SUPPORTED_STEP_SUFFIXES)}), got: {path.suffix or '<none>'}. "
        "If your source is Solid Edge Parasolid (.x_t/.x_b), export as STEP AP242/AP214 first."
    )


@dataclass(frozen=True)
class MeshCollisionReport:
    """Collision result for one mesh pair."""

    a: str
    b: str


def load_step_mesh(
    path: str | Path,
    *,
    linear_deflection: float = 0.001,
    angular_deflection_radians: float = 0.25,
) -> trimesh.Trimesh:
    """Load a STEP file and tessellate into a single trimesh mesh."""
    step_path = Path(path)
    if not step_path.exists():
        raise FileNotFoundError(f"STEP file not found: {step_path}")
    _ensure_supported_step_path(step_path)

    reader = STEPControl_Reader()
    status = reader.ReadFile(str(step_path))
    if status != IFSelect_RetDone:
        raise ValueError(f"Failed to read STEP file: {step_path}")

    transferred = reader.TransferRoots()
    if transferred == 0:
        raise ValueError(f"STEP file had no transferable roots: {step_path}")

    shape = reader.OneShape()
    BRepMesh_IncrementalMesh(shape, linear_deflection, False, angular_deflection_radians, True)

    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []

    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        face = TopoDS.Face_s(explorer.Current())
        location = TopLoc_Location()
        triangulation = BRep_Tool.Triangulation_s(face, location)

        if triangulation is not None:
            transform = location.Transformation()
            vertex_offset = len(vertices)

            for i in range(1, triangulation.NbNodes() + 1):
                point = triangulation.Node(i).Transformed(transform)
                vertices.append((point.X(), point.Y(), point.Z()))

            for i in range(1, triangulation.NbTriangles() + 1):
                tri = triangulation.Triangle(i)
                n1, n2, n3 = tri.Value(1), tri.Value(2), tri.Value(3)
                if face.Orientation() == TopAbs_REVERSED:
                    n1, n2, n3 = n3, n2, n1
                faces.append((vertex_offset + n1 - 1, vertex_offset + n2 - 1, vertex_offset + n3 - 1))

        explorer.Next()

    if not vertices or not faces:
        raise ValueError(f"STEP tessellation yielded no mesh triangles: {step_path}")

    return trimesh.Trimesh(
        vertices=np.asarray(vertices, dtype=float),
        faces=np.asarray(faces, dtype=np.int64),
        process=True,
    )


def detect_mesh_interferences(meshes: dict[str, trimesh.Trimesh]) -> list[MeshCollisionReport]:
    """Return all colliding mesh pairs using python-fcl broad/narrow phase."""
    manager = CollisionManager()
    for name, mesh in meshes.items():
        manager.add_object(name, mesh)

    has_collision, pairs = manager.in_collision_internal(return_names=True)
    if not has_collision:
        return []

    reports = [MeshCollisionReport(a=a, b=b) for a, b in sorted(pairs)]
    return reports


def detect_step_interferences(
    named_step_files: Iterable[tuple[str, str | Path]],
    *,
    linear_deflection: float = 0.001,
    angular_deflection_radians: float = 0.25,
) -> list[MeshCollisionReport]:
    """Load multiple STEP files and report pairwise mesh collisions."""
    meshes = {
        name: load_step_mesh(
            path,
            linear_deflection=linear_deflection,
            angular_deflection_radians=angular_deflection_radians,
        )
        for name, path in named_step_files
    }
    return detect_mesh_interferences(meshes)
