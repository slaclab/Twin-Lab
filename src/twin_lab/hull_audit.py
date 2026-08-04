"""Accuracy audit for the CoACD hulls that stand in for reviewed CAD meshes.

Drake never sees the tessellated part: it sees the hulls cached beside it. This
module measures the difference between the two -- added volume, outward bulge, and
material the hulls fail to cover -- and can draw both together in Meshcat so a number
can be traced back to the shape that produced it. The cached OBJ is the STEP geometry
at the review's tessellation deflection, so it is the reference the hulls are judged
against.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .convex_collision import _content_matches, read_obj_parts
from .paths import CACHE_ROOT, resolve_repo_path

MM_PER_M = 1000.0
# Below this a vertex is on the hull boundary rather than outside it; the OBJ writer
# keeps 9 significant digits, so this is comfortably above the round-trip error.
OUTSIDE_TOLERANCE_M = 1e-6
# Volume overlap is estimated by sampling, so this sets the precision of the reported
# ratio; the correction it feeds is small, so a modest count is enough.
OVERLAP_SAMPLES = 4000
# Point-triangle distance broadcasts points against triangles, so the chunk is chosen
# to bound the intermediate arrays rather than the point count.
DISTANCE_CHUNK_ELEMENTS = 500_000
# Widening steps for that search, as a fraction of the query points' own diagonal.
SEARCH_MARGINS = (0.05, 0.25, 1.0)

HULL_RGBA = (
    (0.20, 0.48, 0.90),
    (0.95, 0.55, 0.12),
    (0.25, 0.75, 0.40),
    (0.85, 0.20, 0.55),
    (0.55, 0.40, 0.85),
    (0.90, 0.80, 0.15),
)
SOURCE_RGBA = (0.62, 0.64, 0.66, 1.0)
HULL_ALPHA = 0.35
PART_LABEL = "Part index"
HULLS_ON = "Hulls: SOLID (click for wireframe)"
HULLS_WIRE = "Hulls: WIREFRAME (click to hide)"
HULLS_OFF = "Hulls: HIDDEN (click for solid)"
SOURCE_ON = "CAD mesh: ON (click to hide)"
SOURCE_OFF = "CAD mesh: OFF (click to show)"


@dataclass(frozen=True)
class Hull:
    """One convex hull with the outward face planes that define its interior."""

    path: Path
    vertices: np.ndarray
    faces: np.ndarray
    normals: np.ndarray
    offsets: np.ndarray
    volume: float


@dataclass(frozen=True)
class PartAudit:
    """How well one part's hulls reproduce the mesh they replace."""

    source: Path
    part_ref: str
    triangles: int
    hull_count: int
    mesh_volume_m3: float
    hull_volume_m3: float
    max_bulge_mm: float
    mean_bulge_mm: float
    max_gap_mm: float
    outside_fraction: float

    @property
    def volume_ratio(self) -> float:
        """Hull volume over mesh volume; 1.0 is a perfect fit, above 1.0 is added material."""

        if self.mesh_volume_m3 <= 0.0:
            return float("inf")
        return self.hull_volume_m3 / self.mesh_volume_m3

    @property
    def label(self) -> str:
        return f"{self.source.stem}/{self.part_ref}"


@dataclass(frozen=True)
class PartGeometry:
    """The reference mesh and hulls for one part, kept for the viewer."""

    audit: PartAudit
    vertices: np.ndarray
    faces: np.ndarray
    hulls: tuple[Hull, ...]


def load_hull(path: Path) -> Hull:
    """Read a cached hull OBJ and derive its outward planes and exact volume."""

    vertices, faces = _read_obj(path)
    a, b, c = vertices[faces[:, 0]], vertices[faces[:, 1]], vertices[faces[:, 2]]
    normals = np.cross(b - a, c - a)
    lengths = np.linalg.norm(normals, axis=1)
    keep = lengths > 0.0
    normals = normals[keep] / lengths[keep, None]
    offsets = -np.einsum("ij,ij->i", normals, a[keep])
    # CoACD's winding is consistent but unverified here; a convex body always contains
    # its own vertex centroid, so that point decides which side of each plane is inside.
    interior = vertices.mean(axis=0)
    flip = normals @ interior + offsets > 0.0
    normals = np.where(flip[:, None], -normals, normals)
    offsets = np.where(flip, -offsets, offsets)
    return Hull(
        path=path,
        vertices=vertices,
        faces=faces,
        normals=normals,
        offsets=offsets,
        volume=mesh_volume(vertices, faces),
    )


def mesh_volume(vertices: np.ndarray, faces: np.ndarray) -> float:
    """Enclosed volume by the divergence theorem, referenced to the mesh's own centroid.

    The tessellation is not watertight: about 1% of its edges bound a sliver crack, and
    the leaked term of this integral grows with the distance from the reference point.
    Referenced to the world origin the same part measured 4,374 mm^3 at one placement
    and 17,520 mm^3 at another; referenced to its centroid both give 106,823 mm^3.
    """

    centered = vertices - vertices.mean(axis=0)
    a, b, c = centered[faces[:, 0]], centered[faces[:, 1]], centered[faces[:, 2]]
    return abs(float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum()) / 6.0)


def union_volume(hulls: Sequence[Hull], rng: np.random.Generator) -> float:
    """Volume of the union, exact per hull with a sampled correction for overlap.

    Summing hull volumes double-counts every overlap, and CoACD's pieces do overlap.
    Each hull after the first contributes only the fraction of itself that no earlier
    hull already covers, which is unbiased and needs sampling only inside that hull.
    """

    ordered = sorted(hulls, key=lambda hull: hull.volume, reverse=True)
    total = 0.0
    for index, hull in enumerate(ordered):
        # Most pieces of a decomposition are disjoint, so only the few that could
        # overlap are worth sampling against.
        neighbours = [other for other in ordered[:index] if _boxes_overlap(hull, other)]
        if not neighbours or hull.volume <= 0.0:
            total += hull.volume
            continue
        points = _sample_inside(hull, OVERLAP_SAMPLES, rng)
        if len(points) == 0:
            total += hull.volume
            continue
        covered = np.zeros(len(points), dtype=bool)
        for earlier in neighbours:
            covered |= _inside_mask(earlier, points)
        total += hull.volume * float(1.0 - covered.mean())
    return total


def outside_distance(hulls: Sequence[Hull], points: np.ndarray) -> np.ndarray:
    """Distance from each point to the nearest hull, or zero when inside one.

    The per-hull value is the largest signed plane distance, which is the exact
    distance when the closest feature is a face and a lower bound near an edge, so
    reported gaps never overstate the missing material.
    """

    if not hulls or len(points) == 0:
        return np.zeros(len(points))
    per_hull = np.stack(
        [(points @ hull.normals.T + hull.offsets).max(axis=1) for hull in hulls], axis=1
    )
    return np.maximum(per_hull.min(axis=1), 0.0)


def surface_distance(points: np.ndarray, vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Signed distance from each point to the mesh: positive outside, negative inside.

    Hull vertices sit on or just off the surface, so the search starts in a box barely
    larger than the points themselves and widens only for the points it cannot settle.
    A point keeps its answer once that answer is smaller than its own margin to the
    box, which is a lower bound on every triangle the box excluded, so the result is
    the same as searching the whole mesh.

    The sign comes from the closest triangle's outward normal. A hull that fills a
    solid region puts vertices deep inside the part, and those are not added material;
    without the sign a well-fitted part reads as badly bulged, which is how P024 of
    static_A003 reported 4.42 mm while its true outward bulge is 0.28 mm.
    """

    if len(points) == 0 or len(faces) == 0:
        return np.zeros(len(points))
    a, b, c = vertices[faces[:, 0]], vertices[faces[:, 1]], vertices[faces[:, 2]]
    normals = np.cross(b - a, c - a)
    lengths = np.linalg.norm(normals, axis=1)
    normals = normals / np.where(lengths > 0.0, lengths, 1.0)[:, None]
    corner_low = np.minimum(np.minimum(a, b), c)
    corner_high = np.maximum(np.maximum(a, b), c)
    span = float(np.linalg.norm(points.max(axis=0) - points.min(axis=0)))
    distances = np.full(len(points), np.inf)
    pending = np.arange(len(points))
    for fraction in SEARCH_MARGINS:
        margin = fraction * span
        lower = points.min(axis=0) - margin
        upper = points.max(axis=0) + margin
        near = ((corner_high >= lower) & (corner_low <= upper)).all(axis=1)
        block = points[pending]
        found = _brute_surface_distance(block, a[near], b[near], c[near], normals[near])
        if near.all():
            distances[pending] = found
            return distances
        settled = np.abs(found) <= np.minimum(block - lower, upper - block).min(axis=1)
        distances[pending[settled]] = found[settled]
        pending = pending[~settled]
        if len(pending) == 0:
            return distances
    distances[pending] = _brute_surface_distance(points[pending], a, b, c, normals)
    return distances


def _brute_surface_distance(
    points: np.ndarray, a: np.ndarray, b: np.ndarray, c: np.ndarray, normals: np.ndarray
) -> np.ndarray:
    if len(a) == 0:
        return np.full(len(points), np.inf)
    chunk = max(1, DISTANCE_CHUNK_ELEMENTS // len(a))
    out = np.empty(len(points))
    for start in range(0, len(points), chunk):
        block = points[start : start + chunk][:, None, :]
        offset = block - _closest_on_triangle(block, a, b, c)
        lengths = np.linalg.norm(offset, axis=2)
        pick = lengths.argmin(axis=1)
        rows = np.arange(len(pick))
        side = np.einsum("ij,ij->i", offset[rows, pick], normals[pick])
        out[start : start + chunk] = np.where(side < 0.0, -lengths[rows, pick], lengths[rows, pick])
    return out


def audit_part(
    source: Path,
    part_ref: str,
    vertices: np.ndarray,
    faces: np.ndarray,
    hulls: Sequence[Hull],
    rng: np.random.Generator,
) -> PartAudit:
    """Compare one reviewed part against the hulls that replace it."""

    # Per hull rather than all at once: each hull is local, so the prefilter inside
    # surface_distance can discard most of the part's triangles. Only the outward side
    # is added material, so vertices the signed distance places inside contribute zero.
    bulge = (
        np.clip(
            np.concatenate([surface_distance(hull.vertices, vertices, faces) for hull in hulls]),
            0.0,
            None,
        )
        if hulls
        else np.zeros(0)
    )
    gap = outside_distance(hulls, vertices)
    return PartAudit(
        source=source,
        part_ref=part_ref,
        triangles=len(faces),
        hull_count=len(hulls),
        mesh_volume_m3=mesh_volume(vertices, faces),
        hull_volume_m3=union_volume(hulls, rng),
        max_bulge_mm=float(bulge.max()) * MM_PER_M if len(bulge) else 0.0,
        mean_bulge_mm=float(bulge.mean()) * MM_PER_M if len(bulge) else 0.0,
        max_gap_mm=float(gap.max()) * MM_PER_M if len(gap) else 0.0,
        outside_fraction=float((gap > OUTSIDE_TOLERANCE_M).mean()) if len(gap) else 0.0,
    )


def audit_cache(
    cache_dir: Path,
    *,
    sources: Iterable[str] | None = None,
    part_pattern: str | None = None,
    seed: int = 0,
    progress: bool = False,
) -> list[PartGeometry]:
    """Audit every decomposed part recorded under a decomposition cache directory."""

    rng = np.random.default_rng(seed)
    matcher = re.compile(part_pattern, re.IGNORECASE) if part_pattern else None
    wanted = {name.lower() for name in sources} if sources else None
    results: list[PartGeometry] = []
    manifests = sorted(cache_dir.rglob("manifest.json"))
    if not manifests:
        raise FileNotFoundError(f"No decomposition manifests under {cache_dir}")
    for number, manifest_path in enumerate(manifests, start=1):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        source = Path(manifest["source"])
        if wanted is not None and not _matches_source(source, wanted):
            continue
        if not source.exists():
            print(f"  skipped {manifest_path.parent.name}: source mesh is gone ({source})")
            continue
        if not _content_matches(manifest, source):
            print(f"  warning: {source.name} changed since it was decomposed; audit is stale")
        entries = {
            str(item["part_ref"]): item["hulls"]
            for item in manifest["parts"]
            if matcher is None or matcher.search(str(item["part_ref"]))
        }
        if not entries:
            continue
        if progress:
            print(f"  [{number}/{len(manifests)}] {source.stem}: {len(entries)} parts", flush=True)
        for part_ref, part_vertices, part_faces in read_obj_parts(source):
            names = entries.get(part_ref)
            if names is None:
                continue
            vertices = np.asarray(part_vertices, dtype=np.float64)
            faces = np.asarray(part_faces, dtype=np.int32)
            hulls = tuple(load_hull(manifest_path.parent / name) for name in names)
            results.append(
                PartGeometry(
                    audit=audit_part(source, part_ref, vertices, faces, hulls, rng),
                    vertices=vertices,
                    faces=faces,
                    hulls=hulls,
                )
            )
    return results


def format_table(audits: Sequence[PartAudit]) -> str:
    """One line per part, worst fit first."""

    header = (
        f"{'part':<28}{'tris':>7}{'hulls':>6}{'vol x':>8}"
        f"{'bulge mm':>10}{'gap mm':>8}{'outside':>8}"
    )
    lines = [header, "-" * len(header)]
    for audit in audits:
        lines.append(
            f"{audit.label[:27]:<28}{audit.triangles:>7}{audit.hull_count:>6}"
            f"{audit.volume_ratio:>8.3f}{audit.max_bulge_mm:>10.2f}"
            f"{audit.max_gap_mm:>8.3f}{audit.outside_fraction:>8.1%}"
        )
    return "\n".join(lines)


def format_summary(audits: Sequence[PartAudit]) -> str:
    mesh = sum(audit.mesh_volume_m3 for audit in audits)
    hull = sum(audit.hull_volume_m3 for audit in audits)
    ratios = [audit.volume_ratio for audit in audits if audit.mesh_volume_m3 > 0.0]
    return "\n".join(
        [
            f"{len(audits)} parts, {sum(audit.hull_count for audit in audits)} hulls",
            f"Volume: mesh {mesh * 1e9:,.0f} mm^3, hulls {hull * 1e9:,.0f} mm^3 "
            f"({hull / mesh:.3f}x overall)"
            if mesh > 0.0
            else "Volume: mesh is empty",
            f"Volume ratio: median {float(np.median(ratios)):.3f}, "
            f"90th pct {float(np.percentile(ratios, 90)):.3f}, max {max(ratios):.3f}"
            if ratios
            else "Volume ratio: not computable",
            f"Outward bulge: max {max(a.max_bulge_mm for a in audits):.2f} mm, "
            f"mean {float(np.mean([a.mean_bulge_mm for a in audits])):.2f} mm",
            f"Uncovered mesh: max gap {max(a.max_gap_mm for a in audits):.3f} mm, "
            f"{sum(1 for a in audits if a.outside_fraction > 0.0)} parts with any gap",
        ]
    )


def write_csv(path: Path, audits: Sequence[PartAudit]) -> None:
    import csv

    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "source",
                "part_ref",
                "triangles",
                "hulls",
                "mesh_volume_mm3",
                "hull_volume_mm3",
                "volume_ratio",
                "max_bulge_mm",
                "mean_bulge_mm",
                "max_gap_mm",
                "outside_fraction",
            ]
        )
        for audit in audits:
            writer.writerow(
                [
                    audit.source.name,
                    audit.part_ref,
                    audit.triangles,
                    audit.hull_count,
                    f"{audit.mesh_volume_m3 * 1e9:.6g}",
                    f"{audit.hull_volume_m3 * 1e9:.6g}",
                    f"{audit.volume_ratio:.6g}",
                    f"{audit.max_bulge_mm:.6g}",
                    f"{audit.mean_bulge_mm:.6g}",
                    f"{audit.max_gap_mm:.6g}",
                    f"{audit.outside_fraction:.6g}",
                ]
            )


def run_hull_viewer(parts: Sequence[PartGeometry]) -> None:
    """Show one part at a time with its hulls drawn over the CAD mesh."""

    import time

    from pydrake.geometry import Meshcat, MeshcatParams, Rgba

    from .stage_cad_viewer import _wsl_ipv4_address

    params = MeshcatParams(host="*")
    address = _wsl_ipv4_address()
    if address is not None:
        params.web_url_pattern = f"http://{address}:{{port}}"
    meshcat = Meshcat(params)
    print(f"Hull audit viewer: {meshcat.web_url()}")
    print(f"Uploading {len(parts)} parts")

    paths: list[str] = []
    for index, part in enumerate(parts):
        root = f"/audit/part{index:03d}"
        paths.append(root)
        meshcat.SetTriangleMesh(
            f"{root}/mesh",
            _columns(part.vertices),
            _indices(part.faces),
            Rgba(*SOURCE_RGBA),
        )
        for hull_index, hull in enumerate(part.hulls):
            red, green, blue = HULL_RGBA[hull_index % len(HULL_RGBA)]
            vertices, faces = _columns(hull.vertices), _indices(hull.faces)
            meshcat.SetTriangleMesh(
                f"{root}/hulls/{hull_index:03d}",
                vertices,
                faces,
                Rgba(red, green, blue, HULL_ALPHA),
            )
            meshcat.SetTriangleMesh(
                f"{root}/wire/{hull_index:03d}",
                vertices,
                faces,
                Rgba(red, green, blue, 1.0),
                True,
            )
        meshcat.SetProperty(root, "visible", False)

    meshcat.AddSlider(PART_LABEL, 0.0, float(len(parts) - 1), 1.0, 0.0)
    meshcat.AddButton("Stop viewer", "Escape")
    hull_button = HULLS_ON
    source_button = SOURCE_ON
    meshcat.AddButton(hull_button)
    meshcat.AddButton(source_button)
    print("Use the Part index slider to step through parts, worst fit first.")
    print("Blue/orange shells are the hulls Drake collides with; grey is the CAD mesh.")
    print("Press Escape in Meshcat or Ctrl-C here to stop.")

    hull_style = 0
    source_visible = True
    current = -1
    hull_clicks = 0
    source_clicks = 0
    while meshcat.GetButtonClicks("Stop viewer") == 0:
        new_hull = meshcat.GetButtonClicks(hull_button)
        new_source = meshcat.GetButtonClicks(source_button)
        index = min(max(int(round(meshcat.GetSliderValue(PART_LABEL))), 0), len(parts) - 1)
        changed = index != current
        if changed:
            if current >= 0:
                meshcat.SetProperty(paths[current], "visible", False)
            current = index
            meshcat.SetProperty(paths[current], "visible", True)
            _frame_camera(meshcat, parts[index])
            print(_describe(index, parts[index].audit))
        if new_hull != hull_clicks:
            hull_clicks = new_hull
            hull_style = (hull_style + 1) % 3
            meshcat.DeleteButton(hull_button)
            hull_button = (HULLS_ON, HULLS_WIRE, HULLS_OFF)[hull_style]
            meshcat.AddButton(hull_button)
            changed = True
        if new_source != source_clicks:
            source_clicks = new_source
            source_visible = not source_visible
            meshcat.DeleteButton(source_button)
            source_button = SOURCE_ON if source_visible else SOURCE_OFF
            meshcat.AddButton(source_button)
            changed = True
        if changed:
            root = paths[current]
            meshcat.SetProperty(f"{root}/hulls", "visible", hull_style == 0)
            meshcat.SetProperty(f"{root}/wire", "visible", hull_style == 1)
            meshcat.SetProperty(f"{root}/mesh", "visible", source_visible)
        time.sleep(0.05)


def _describe(index: int, audit: PartAudit) -> str:
    return (
        f"[{index}] {audit.label}: {audit.hull_count} hulls, "
        f"volume {audit.volume_ratio:.3f}x, bulge {audit.max_bulge_mm:.2f} mm, "
        f"gap {audit.max_gap_mm:.3f} mm"
    )


def _frame_camera(meshcat, part: PartGeometry) -> None:
    lower, upper = part.vertices.min(axis=0), part.vertices.max(axis=0)
    center = (lower + upper) / 2.0
    span = max(float(np.linalg.norm(upper - lower)), 1e-3)
    eye = center + np.array([0.7, -0.9, 0.6]) * span
    # pydrake's stub gives SetCameraPose a malformed Eigen shape; lists convert at runtime.
    meshcat.SetCameraPose(eye.tolist(), center.tolist())  # pyright: ignore[reportArgumentType]


def _columns(vertices: np.ndarray) -> np.ndarray:
    return np.asfortranarray(vertices.T.astype(np.float64))


def _indices(faces: np.ndarray) -> np.ndarray:
    return np.asfortranarray(faces.T.astype(np.int32))


def _matches_source(source: Path, wanted: set[str]) -> bool:
    return {source.name.lower(), source.stem.lower(), str(source).lower()} & wanted != set()


def _read_obj(path: Path) -> tuple[np.ndarray, np.ndarray]:
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    for line in path.read_text(encoding="ascii").splitlines():
        if line.startswith("v "):
            x, y, z = (float(value) for value in line[2:].split())
            vertices.append((x, y, z))
        elif line.startswith("f "):
            indices = [int(value.split("/")[0]) - 1 for value in line[2:].split()]
            faces.extend(
                (indices[0], indices[step], indices[step + 1])
                for step in range(1, len(indices) - 1)
            )
    return np.asarray(vertices, dtype=np.float64), np.asarray(faces, dtype=np.int32)


def _inside_mask(hull: Hull, points: np.ndarray) -> np.ndarray:
    return (points @ hull.normals.T + hull.offsets <= 0.0).all(axis=1)


def _boxes_overlap(first: Hull, second: Hull) -> bool:
    return bool(
        (first.vertices.min(axis=0) <= second.vertices.max(axis=0)).all()
        and (second.vertices.min(axis=0) <= first.vertices.max(axis=0)).all()
    )


def _sample_inside(hull: Hull, count: int, rng: np.random.Generator) -> np.ndarray:
    """Rejection-sample uniform points inside a convex hull using its bounding box."""

    lower, upper = hull.vertices.min(axis=0), hull.vertices.max(axis=0)
    kept: list[np.ndarray] = []
    found = 0
    for _ in range(8):
        batch = rng.uniform(lower, upper, size=(count, 3))
        inside = batch[_inside_mask(hull, batch)]
        kept.append(inside)
        found += len(inside)
        if found >= count:
            break
    return np.concatenate(kept)[:count] if kept else np.zeros((0, 3))


def _closest_on_triangle(
    points: np.ndarray, a: np.ndarray, b: np.ndarray, c: np.ndarray
) -> np.ndarray:
    """Closest point on each triangle for each point, by Voronoi region (Ericson)."""

    ab, ac = b - a, c - a
    ap = points - a
    d1 = np.einsum("ijk,jk->ij", ap, ab)
    d2 = np.einsum("ijk,jk->ij", ap, ac)
    bp = points - b
    d3 = np.einsum("ijk,jk->ij", bp, ab)
    d4 = np.einsum("ijk,jk->ij", bp, ac)
    cp = points - c
    d5 = np.einsum("ijk,jk->ij", cp, ab)
    d6 = np.einsum("ijk,jk->ij", cp, ac)

    va = d3 * d6 - d5 * d4
    vb = d5 * d2 - d1 * d6
    vc = d1 * d4 - d3 * d2
    denom = _safe(va + vb + vc)
    v = (vb / denom)[..., None]
    w = (vc / denom)[..., None]
    closest = a + ab * v + ac * w

    # Applied in reverse priority so the earlier checks of the reference algorithm win.
    edge_bc = (d4 - d3) / _safe((d4 - d3) + (d5 - d6))
    closest = np.where(
        ((va <= 0.0) & ((d4 - d3) >= 0.0) & ((d5 - d6) >= 0.0))[..., None],
        b + (c - b) * edge_bc[..., None],
        closest,
    )
    closest = np.where(
        ((vb <= 0.0) & (d2 >= 0.0) & (d6 <= 0.0))[..., None],
        a + ac * (d2 / _safe(d2 - d6))[..., None],
        closest,
    )
    closest = np.where(((d6 >= 0.0) & (d5 <= d6))[..., None], np.broadcast_to(c, closest.shape),
                       closest)
    closest = np.where(
        ((vc <= 0.0) & (d1 >= 0.0) & (d3 <= 0.0))[..., None],
        a + ab * (d1 / _safe(d1 - d3))[..., None],
        closest,
    )
    closest = np.where(((d3 >= 0.0) & (d4 <= d3))[..., None], np.broadcast_to(b, closest.shape),
                       closest)
    return np.where(((d1 <= 0.0) & (d2 <= 0.0))[..., None], np.broadcast_to(a, closest.shape),
                    closest)


def _safe(values: np.ndarray) -> np.ndarray:
    """Keep degenerate triangles from dividing by zero; their branch is discarded anyway."""

    return np.where(values == 0.0, 1.0, values)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Measure how closely cached CoACD hulls match the CAD meshes they replace"
    )
    parser.add_argument(
        "meshes",
        nargs="*",
        help="Restrict to these cached source OBJs (name or stem); default is every mesh",
    )
    parser.add_argument(
        "--cache-dir",
        default=None,
        help="Decomposition cache to audit (default: .cache/twin_lab/convex-collision)",
    )
    parser.add_argument("--part", default=None, help="Regular expression matching part refs")
    parser.add_argument("--top", type=int, default=25, help="Rows to print, worst fit first")
    parser.add_argument(
        "--sort",
        choices=["volume", "bulge", "gap", "hulls"],
        default="volume",
        help="Metric that defines the worst parts",
    )
    parser.add_argument("--csv", default=None, help="Write every audited part to this CSV")
    parser.add_argument("--view", action="store_true", help="Show the worst parts in Meshcat")
    parser.add_argument(
        "--view-limit", type=int, default=12, help="Parts to upload to the viewer"
    )
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    cache_dir = (
        resolve_repo_path(args.cache_dir) if args.cache_dir else CACHE_ROOT / "convex-collision"
    )
    print(f"Auditing hulls in {cache_dir}")
    parts = audit_cache(
        cache_dir,
        sources=args.meshes or None,
        part_pattern=args.part,
        seed=args.seed,
        progress=True,
    )
    if not parts:
        raise SystemExit("No decomposed parts matched")

    keys = {
        "volume": lambda part: part.audit.volume_ratio,
        "bulge": lambda part: part.audit.max_bulge_mm,
        "gap": lambda part: part.audit.max_gap_mm,
        "hulls": lambda part: part.audit.hull_count,
    }
    parts.sort(key=keys[args.sort], reverse=True)
    audits = [part.audit for part in parts]
    print()
    print(format_table(audits[: args.top]))
    if len(audits) > args.top:
        print(f"... {len(audits) - args.top} more parts")
    print()
    print(format_summary(audits))
    print()
    print("vol x  = hull volume / CAD volume, so 1.00 is an exact fit")
    print("bulge  = furthest a hull vertex sits from the CAD surface (added material)")
    print("gap    = furthest a CAD vertex sits outside every hull (missing material)")

    if args.csv:
        destination = Path(args.csv)
        write_csv(destination, audits)
        print(f"Wrote {destination}")
    if args.view:
        run_hull_viewer(parts[: args.view_limit])
