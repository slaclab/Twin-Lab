"""Re-check a flagged pair against geometry closer to the CAD than the hulls Drake sees.

Drake collides with the CoACD hulls, and a hull is always at least as large as the part
it stands in for, so a contact of a millimetre or two can be the decomposition's own
error rather than an interference. Two corrections live here, both applied only to pairs
that are already flagged so the cost stays interactive:

* the measured proudness of the two hulls where they meet, subtracted from the reported
  distance. The numbers come from the ``audit.npz`` that ``slac-hull-audit`` writes, so
  this costs a dictionary lookup and is exact for the hull vertices it was measured at.
* the exact distance between the two tessellated parts themselves, computed over the
  triangles around the witness points. This removes decomposition error entirely and
  leaves only the tessellation deflection the meshes were built at.

Neither result should clear a pair on its own. Both are evidence that an interference is
an artefact of the collision geometry, which is a prompt to look at the CAD rather than a
measurement of the hardware.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from .convex_collision import read_obj_parts
from .hull_audit import (
    AUDIT_CACHE_NAME,
    MM_PER_M,
    _audit_key,
    _closest_on_triangle,
    _read_audit_cache,
    _read_obj,
)

if TYPE_CHECKING:
    from .collision import Clearance

# Contacts are flagged inside a band of a few millimetres, so the true closest features
# are far inside this. It only has to be wide enough that the answer is not truncated.
DEFAULT_RADIUS_M = 0.02
# Bounds the triangle-pair arrays. The kept triangles are the ones nearest the witness
# point, so a truncated neighbourhood still holds the closest features.
MAX_TRIANGLES = 400
# Rows of the edge-pair distance computed at once, to bound its intermediates.
EDGE_CHUNK = 128
# The witness point lies on a hull face, so its bulge is interpolated from the vertices
# of that face rather than read off the nearest one.
BULGE_NEIGHBOURS = 3
PARALLEL_EPSILON = 1e-15
# sdf_compiler names each hull ``<link>_<part>_<hull index>_collision``, zero-padding the
# index to three digits. Requiring the padding keeps a link name that happens to end in a
# digit from being read as a hull; the suffix is optional so a bare piece name also parses.
HULL_INDEX_PATTERN = re.compile(r"_(\d{3,})(?:_collision)?$")


@dataclass(frozen=True)
class Refinement:
    """One flagged pair, re-checked against something closer to the CAD than its hulls."""

    parts: tuple[str, str]
    hull_distance_m: float
    bulge_m: float | None
    mesh_distance_m: float | None

    @property
    def corrected_m(self) -> float | None:
        """The reported distance with the two hulls' local proudness taken back off."""

        if self.bulge_m is None:
            return None
        return self.hull_distance_m + self.bulge_m

    @property
    def evidence(self) -> str:
        if self.mesh_distance_m is not None:
            return "mesh"
        return "bulge" if self.bulge_m is not None else "none"

    @property
    def verdict(self) -> str:
        """``contact`` when the pair survives the correction, ``explained`` when it does not."""

        if self.mesh_distance_m is not None:
            return "contact" if self.mesh_distance_m <= 0.0 else "explained"
        if self.corrected_m is not None:
            return "contact" if self.corrected_m <= 0.0 else "explained"
        return "unverified"

    def describe(self) -> str:
        first, second = self.parts
        head = f"{first} <-> {second}: hulls {self.hull_distance_m * MM_PER_M:+.2f} mm"
        if self.mesh_distance_m is not None:
            if self.mesh_distance_m <= 0.0:
                return f"{head}; CAD meshes intersect -> CONTACT"
            return (
                f"{head}; CAD meshes {self.mesh_distance_m * MM_PER_M:.2f} mm apart"
                " -> explained by hull proudness"
            )
        if self.bulge_m is not None and self.corrected_m is not None:
            state = "CONTACT" if self.corrected_m <= 0.0 else "explained by hull proudness"
            return (
                f"{head}; local proudness {self.bulge_m * MM_PER_M:.2f} mm"
                f" -> {self.corrected_m * MM_PER_M:+.2f} mm -> {state}"
            )
        return f"{head}; nothing cached to check it against -> unverified"


@dataclass(frozen=True)
class _PartEntry:
    """Where one reviewed part's tessellation and hulls are cached."""

    directory: Path
    source: Path
    hulls: tuple[str, ...]


class ClearanceRefiner:
    """Cached access to the meshes and audited proudness behind the compiled hulls."""

    def __init__(self, cache_dir: str | Path, *, seed: int = 0):
        self.cache_dir = Path(cache_dir)
        self.seed = seed
        self._parts = _index_parts(self.cache_dir)
        self._meshes: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        self._hulls: dict[str, tuple[np.ndarray, ...]] = {}
        self._bulge: dict[str, np.ndarray | None] = {}

    def __len__(self) -> int:
        return len(self._parts)

    def refine(
        self,
        clearance: Clearance,
        *,
        radius_m: float = DEFAULT_RADIUS_M,
        with_mesh: bool = True,
    ) -> Refinement:
        """Correct one clearance, using the CAD tessellations when they can be loaded."""

        first, second = (part.upper() for part in clearance.parts)
        bulge = _sum_or_none(
            self.local_bulge_m(first, clearance.a, clearance.witness_a_m, clearance.pose_a),
            self.local_bulge_m(second, clearance.b, clearance.witness_b_m, clearance.pose_b),
        )
        mesh_distance = None
        if with_mesh:
            mesh_distance = self.mesh_distance_m(
                (first, clearance.witness_a_m, clearance.pose_a),
                (second, clearance.witness_b_m, clearance.pose_b),
                radius_m=radius_m,
            )
        return Refinement(
            parts=(first, second),
            hull_distance_m=clearance.distance_m,
            bulge_m=bulge,
            mesh_distance_m=mesh_distance,
        )

    def local_bulge_m(
        self,
        part_ref: str,
        geometry_name: str,
        witness_m: np.ndarray | None,
        pose: np.ndarray | None,
    ) -> float | None:
        """How far the hull in contact stands off the CAD surface, at the contact itself."""

        index = _hull_index(geometry_name)
        bulge = self._part_bulge(part_ref)
        hulls = self._part_hulls(part_ref)
        if bulge is None or index is None or index >= len(hulls):
            return None
        start = sum(len(hull) for hull in hulls[:index])
        vertices = hulls[index]
        local = bulge[start : start + len(vertices)]
        if len(local) != len(vertices) or len(local) == 0:
            return None
        if witness_m is None or pose is None:
            return float(local.mean())
        point = _to_local(pose, witness_m)
        nearest = np.argsort(np.linalg.norm(vertices - point, axis=1))[:BULGE_NEIGHBOURS]
        return float(local[nearest].mean())

    def mesh_distance_m(
        self,
        a: tuple[str, np.ndarray | None, np.ndarray | None],
        b: tuple[str, np.ndarray | None, np.ndarray | None],
        *,
        radius_m: float = DEFAULT_RADIUS_M,
    ) -> float | None:
        """Exact distance between the two tessellated parts, or ``None`` without meshes."""

        first = self._neighbourhood(*a, radius_m)
        second = self._neighbourhood(*b, radius_m)
        if first is None or second is None:
            return None
        return mesh_separation_m(*first, *second)

    def _neighbourhood(
        self,
        part_ref: str,
        witness_m: np.ndarray | None,
        pose: np.ndarray | None,
        radius_m: float,
    ) -> tuple[np.ndarray, np.ndarray] | None:
        mesh = self._part_mesh(part_ref)
        if mesh is None or pose is None or witness_m is None:
            return None
        vertices, faces = mesh
        world = vertices @ pose[:3, :3].T + pose[:3, 3]
        return world, triangles_near(world, faces, witness_m, radius_m)

    def _part_mesh(self, part_ref: str) -> tuple[np.ndarray, np.ndarray] | None:
        """The reviewed part's own triangles, in the frame its hulls were cut from."""

        if part_ref in self._meshes:
            return self._meshes[part_ref]
        entry = self._parts.get(part_ref)
        if entry is None or not entry.source.exists():
            return None
        # One source OBJ holds every part of a sub-assembly, so parsing it once for a
        # single part and discarding the rest would re-parse it for the next flag.
        for reference, vertices, faces in read_obj_parts(entry.source):
            self._meshes[reference.upper()] = (
                np.asarray(vertices, dtype=np.float64),
                np.asarray(faces, dtype=np.int32),
            )
        return self._meshes.get(part_ref)

    def _part_hulls(self, part_ref: str) -> tuple[np.ndarray, ...]:
        if part_ref not in self._hulls:
            entry = self._parts.get(part_ref)
            self._hulls[part_ref] = (
                ()
                if entry is None
                else tuple(_read_obj(entry.directory / name)[0] for name in entry.hulls)
            )
        return self._hulls[part_ref]

    def _part_bulge(self, part_ref: str) -> np.ndarray | None:
        """Audited bulge per hull vertex, or ``None`` until ``slac-hull-audit`` has run."""

        if part_ref in self._bulge:
            return self._bulge[part_ref]
        entry = self._parts.get(part_ref)
        measured = {}
        if entry is not None:
            manifest = _read_manifest(entry.directory)
            if manifest is not None:
                measured = _read_audit_cache(
                    entry.directory / AUDIT_CACHE_NAME,
                    _audit_key(manifest, self.seed),
                    entry.source,
                )
        for reference, (_, fit) in measured.items():
            self._bulge[reference.upper()] = fit.bulge_m
        self._bulge.setdefault(part_ref, None)
        return self._bulge[part_ref]


def mesh_separation_m(
    a_vertices: np.ndarray,
    a_faces: np.ndarray,
    b_vertices: np.ndarray,
    b_faces: np.ndarray,
) -> float:
    """Smallest distance between two tessellations, or zero where they intersect.

    Two disjoint triangles are closest either along a pair of edges or between a vertex
    of one and the face of the other, so those candidates give the exact distance. They
    do not detect an edge passing through a face, which is what interpenetration looks
    like, so that case is tested for separately and reported as touching.
    """

    if len(a_faces) == 0 or len(b_faces) == 0:
        return float("inf")
    a_corners = a_vertices[a_faces]
    b_corners = b_vertices[b_faces]
    if _pierces(a_corners, b_corners) or _pierces(b_corners, a_corners):
        return 0.0
    return min(
        _edge_distance(a_corners, b_corners),
        _vertex_face_distance(np.unique(a_faces), a_vertices, b_corners),
        _vertex_face_distance(np.unique(b_faces), b_vertices, a_corners),
    )


def triangles_near(
    vertices: np.ndarray, faces: np.ndarray, point: np.ndarray, radius_m: float
) -> np.ndarray:
    """Faces whose bounding box reaches within ``radius_m`` of a point, nearest first."""

    if len(faces) == 0:
        return faces
    corners = vertices[faces]
    lower = corners.min(axis=1)
    upper = corners.max(axis=1)
    outside = np.maximum(lower - point, 0.0) + np.maximum(point - upper, 0.0)
    distance = np.linalg.norm(outside, axis=1)
    near = np.flatnonzero(distance <= radius_m)
    if len(near) <= MAX_TRIANGLES:
        return faces[near]
    return faces[near[np.argsort(distance[near])[:MAX_TRIANGLES]]]


def _pierces(edge_corners: np.ndarray, face_corners: np.ndarray) -> bool:
    """Whether any edge of one mesh passes through a triangle of the other.

    Moller-Trumbore, with the ray parameter confined to the edge. Two triangles that are
    not coplanar intersect only if an edge of one crosses the other, so this is the whole
    test for the tessellations of two solids.
    """

    start, end = _edges(edge_corners)
    direction = end - start
    a, b, c = face_corners[:, 0], face_corners[:, 1], face_corners[:, 2]
    first, second = b - a, c - a
    for begin in range(0, len(start), EDGE_CHUNK):
        block = slice(begin, begin + EDGE_CHUNK)
        heading = direction[block][:, None, :]
        cross = np.cross(heading, second[None, :, :])
        determinant = np.einsum("ijk,jk->ij", cross, first)
        parallel = np.abs(determinant) < PARALLEL_EPSILON
        inverse = 1.0 / np.where(parallel, 1.0, determinant)
        offset = start[block][:, None, :] - a[None, :, :]
        u = inverse * np.einsum("ijk,ijk->ij", offset, cross)
        edge_cross = np.cross(offset, first[None, :, :])
        v = inverse * np.einsum("ijk,ijk->ij", heading, edge_cross)
        t = inverse * np.einsum("ijk,jk->ij", edge_cross, second)
        hit = ~parallel & (u >= 0.0) & (v >= 0.0) & (u + v <= 1.0) & (t >= 0.0) & (t <= 1.0)
        if hit.any():
            return True
    return False


def _edge_distance(a_corners: np.ndarray, b_corners: np.ndarray) -> float:
    a_start, a_end = _edges(a_corners)
    b_start, b_end = _edges(b_corners)
    best = float("inf")
    for begin in range(0, len(a_start), EDGE_CHUNK):
        block = slice(begin, begin + EDGE_CHUNK)
        best = min(
            best,
            _segment_distance(a_start[block], a_end[block], b_start, b_end),
        )
    return best


def _edges(corners: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    start = np.concatenate([corners[:, i] for i in range(3)])
    end = np.concatenate([corners[:, (i + 1) % 3] for i in range(3)])
    return start, end


def _segment_distance(
    a_start: np.ndarray, a_end: np.ndarray, b_start: np.ndarray, b_end: np.ndarray
) -> float:
    """Smallest distance between any segment of one set and any of the other."""

    first = (a_end - a_start)[:, None, :]
    second = (b_end - b_start)[None, :, :]
    offset = a_start[:, None, :] - b_start[None, :, :]
    a = (first * first).sum(-1)
    e = (second * second).sum(-1)
    b = (first * second).sum(-1)
    c = (first * offset).sum(-1)
    f = (second * offset).sum(-1)
    denominator = a * e - b * b
    # Parallel segments leave the pair undetermined, so one end is pinned and the other
    # solved for, which the clamping below does anyway.
    s = np.where(
        denominator > PARALLEL_EPSILON,
        (b * f - c * e) / np.where(denominator > PARALLEL_EPSILON, denominator, 1.0),
        0.0,
    )
    s = np.clip(s, 0.0, 1.0)
    t = np.clip((b * s + f) / np.where(e > 0.0, e, 1.0), 0.0, 1.0)
    s = np.clip((b * t - c) / np.where(a > 0.0, a, 1.0), 0.0, 1.0)
    gap = offset + first * s[..., None] - second * t[..., None]
    return float(np.linalg.norm(gap, axis=-1).min())


def _vertex_face_distance(used: np.ndarray, vertices: np.ndarray, corners: np.ndarray) -> float:
    points = vertices[used][:, None, :]
    a, b, c = corners[:, 0], corners[:, 1], corners[:, 2]
    best = float("inf")
    for begin in range(0, len(points), EDGE_CHUNK):
        block = points[begin : begin + EDGE_CHUNK]
        offset = block - _closest_on_triangle(block, a, b, c)
        best = min(best, float(np.linalg.norm(offset, axis=2).min()))
    return best


def _index_parts(cache_dir: Path) -> dict[str, _PartEntry]:
    """Map every decomposed part ref to the source mesh and hulls cached for it."""

    index: dict[str, _PartEntry] = {}
    if not cache_dir.is_dir():
        return index
    for manifest_path in sorted(cache_dir.rglob("manifest.json")):
        manifest = _read_manifest(manifest_path.parent)
        if manifest is None:
            continue
        source = Path(manifest["source"])
        for item in manifest.get("parts", []):
            index.setdefault(
                str(item["part_ref"]).upper(),
                _PartEntry(
                    directory=manifest_path.parent,
                    source=source,
                    hulls=tuple(item["hulls"]),
                ),
            )
    return index


def _read_manifest(directory: Path) -> dict | None:
    try:
        return json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _hull_index(geometry_name: str) -> int | None:
    match = HULL_INDEX_PATTERN.search(geometry_name.rsplit("::", 1)[-1])
    return int(match.group(1)) if match else None


def _to_local(pose: np.ndarray, point: np.ndarray) -> np.ndarray:
    return pose[:3, :3].T @ (np.asarray(point, dtype=float) - pose[:3, 3])


def _sum_or_none(first: float | None, second: float | None) -> float | None:
    """Both sides must be measured; half a correction would understate the error."""

    if first is None or second is None:
        return None
    return first + second
