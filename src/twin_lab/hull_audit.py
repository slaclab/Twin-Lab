"""Accuracy audit for the CoACD hulls that stand in for reviewed CAD meshes.

Drake never sees the tessellated part: it sees the hulls cached beside it. This
module measures the difference between the two -- added volume, outward bulge, and
material the hulls fail to cover -- and can draw both together in Meshcat so a number
can be traced back to the shape that produced it. The cached OBJ is the STEP geometry
at the review's tessellation deflection, so it is the reference the hulls are judged
against.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .convex_collision import _content_matches, hull_names, read_obj_parts
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
FOCUS_LABEL = "Focus part index"
WORST_LABEL = "Show worst N parts"
HULLS_PIECE = "Hulls: PIECE COLOURS (click for bulge shading)"
HULLS_BULGE = "Hulls: BULGE SHADING (click to hide)"
HULLS_HIDDEN = "Hulls: HIDDEN (click for piece colours)"
TOUR_NEXT = "Next part (right arrow)"
TOUR_PREVIOUS = "Previous part (left arrow)"
# A review driven part by part gets abandoned if it is long; ten is what a reviewer will
# actually click through, and the tail past it is rarely where the problems are.
TOUR_DEFAULT_COUNT = 10
# Grey where the hull lies on the CAD surface, through amber, to red at the full scale.
BULGE_RAMP_RGB = ((0.62, 0.64, 0.66), (0.95, 0.62, 0.05), (0.88, 0.05, 0.05))
# Where each of those sits on the scale. The grey stop is held out to the tessellation
# deflection because bulge under it is meshing noise, not material CoACD added: the
# median hull vertex of static_A003 bulges 0.17 mm, so a ramp starting at zero paints
# the whole assembly amber and separates nothing.
BULGE_RAMP_STOPS = (0.25, 0.6, 1.0)
DEFAULT_BULGE_SCALE_MM = 2.0

# Measuring a part costs seconds and reading its hulls costs milliseconds, so the
# distances are cached beside the decomposition they judge and die with it.
AUDIT_CACHE_NAME = "audit.npz"
# Bump when a measurement changes meaning, so old numbers are redone rather than trusted.
AUDIT_SCHEMA = 1
# Exact gaps hold a point-by-triangle array, so they are measured a block at a time.
GAP_CHUNK = 512


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
class PartFit:
    """Where a part misfits rather than by how much: the per-vertex errors behind the audit."""

    bulge_m: np.ndarray
    gap_m: np.ndarray


@dataclass(frozen=True)
class PartGeometry:
    """The reference mesh and hulls for one part, kept for the viewer."""

    audit: PartAudit
    vertices: np.ndarray
    faces: np.ndarray
    hulls: tuple[Hull, ...]
    fit: PartFit


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


def surface_gap(hulls: Sequence[Hull], points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Exact distance from each point to the nearest hull, and which hull that is.

    ``outside_distance`` measures to the nearest face *plane*, which falls short of the
    truth whenever the closest feature is an edge or a corner. That understatement is
    harmless when reporting a gap - it never overstates the missing material - but it is
    not safe to inflate by, because growing a hull by the plane distance can still leave
    the point outside. Points inside a hull report zero distance and hull ``-1``.
    """

    distance = np.zeros(len(points))
    nearest = np.full(len(points), -1, dtype=np.int64)
    if not hulls or len(points) == 0:
        return distance, nearest
    outside = np.flatnonzero(outside_distance(hulls, points) > 0.0)
    for start in range(0, len(outside), GAP_CHUNK):
        block = outside[start : start + GAP_CHUNK]
        query = points[block][:, None, :]
        best = np.full(len(block), np.inf)
        owner = np.full(len(block), -1, dtype=np.int64)
        for index, hull in enumerate(hulls):
            corners = tuple(hull.vertices[hull.faces[:, axis]] for axis in range(3))
            closest = _closest_on_triangle(query, *corners)
            span = np.linalg.norm(closest - query, axis=2).min(axis=1)
            owner = np.where(span < best, index, owner)
            best = np.minimum(best, span)
        distance[block] = best
        nearest[block] = owner
    return distance, nearest


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


def part_fit(
    vertices: np.ndarray, faces: np.ndarray, hulls: Sequence[Hull]
) -> PartFit:
    """Per-vertex misfit: outward bulge per hull vertex, uncovered gap per mesh vertex."""

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
    return PartFit(bulge_m=bulge, gap_m=outside_distance(hulls, vertices))


def audit_part(
    source: Path,
    part_ref: str,
    vertices: np.ndarray,
    faces: np.ndarray,
    hulls: Sequence[Hull],
    rng: np.random.Generator,
    fit: PartFit | None = None,
) -> PartAudit:
    """Compare one reviewed part against the hulls that replace it."""

    fit = fit if fit is not None else part_fit(vertices, faces, hulls)
    bulge, gap = fit.bulge_m, fit.gap_m
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
    refresh: bool = False,
) -> list[PartGeometry]:
    """Audit every decomposed part recorded under a decomposition cache directory."""

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
            str(item["part_ref"]): hull_names(item)
            for item in manifest["parts"]
            if matcher is None or matcher.search(str(item["part_ref"]))
        }
        if not entries:
            continue
        cache_path = manifest_path.parent / AUDIT_CACHE_NAME
        key = _audit_key(manifest, seed)
        cached = {} if refresh else _read_audit_cache(cache_path, key, source)
        pending = sum(1 for part_ref in entries if part_ref not in cached)
        if progress:
            state = f"measuring {pending}" if pending else "cached"
            print(
                f"  [{number}/{len(manifests)}] {source.stem}: {len(entries)} parts, {state}",
                flush=True,
            )
        measured = dict(cached)
        for part_ref, part_vertices, part_faces in read_obj_parts(source):
            names = entries.get(part_ref)
            if names is None:
                continue
            vertices = np.asarray(part_vertices, dtype=np.float64)
            faces = np.asarray(part_faces, dtype=np.int32)
            hulls = tuple(load_hull(manifest_path.parent / name) for name in names)
            found = cached.get(part_ref)
            if found is None:
                fit = part_fit(vertices, faces, hulls)
                rng = _part_rng(seed, source, part_ref)
                found = (audit_part(source, part_ref, vertices, faces, hulls, rng, fit), fit)
                measured[part_ref] = found
            audit, fit = found
            results.append(
                PartGeometry(
                    audit=audit,
                    vertices=vertices,
                    faces=faces,
                    hulls=hulls,
                    fit=fit,
                )
            )
        if len(measured) > len(cached):
            _write_audit_cache(cache_path, key, measured)
    return results


def _part_rng(seed: int, source: Path, part_ref: str) -> np.random.Generator:
    """Seeded per part, so a part measures the same whether or not its neighbours were cached."""

    digest = hashlib.blake2b(f"{source}\0{part_ref}".encode(), digest_size=8).digest()
    return np.random.default_rng([seed, int.from_bytes(digest, "big")])


def _audit_key(manifest: dict[str, Any], seed: int) -> str:
    """Everything the numbers depend on: which mesh, which hulls, and how they were measured."""

    return json.dumps(
        {
            "schema": AUDIT_SCHEMA,
            "source_sha256": manifest.get("source_sha256"),
            "source_size": manifest.get("source_size"),
            "parts_settings_sig": manifest.get("parts_settings_sig"),
            # Named explicitly: inflation swaps the hulls without touching the source or
            # the CoACD settings, so a key built from those alone replays stale numbers
            # and the pass looks like it did nothing.
            "hulls": {
                str(item["part_ref"]): hull_names(item) for item in manifest.get("parts", [])
            },
            "seed": seed,
            "overlap_samples": OVERLAP_SAMPLES,
        },
        sort_keys=True,
    )


def _read_audit_cache(path: Path, key: str, source: Path) -> dict[str, tuple[PartAudit, PartFit]]:
    """Measurements from an earlier run, or nothing at all if any input to them changed."""

    if not path.exists():
        return {}
    try:
        with np.load(path, allow_pickle=False) as data:
            if str(data["key"]) != key:
                return {}
            header = json.loads(str(data["header"]))
            return {
                record["part_ref"]: (
                    PartAudit(source=source, **record),
                    PartFit(bulge_m=data[f"{index}.bulge"], gap_m=data[f"{index}.gap"]),
                )
                for index, record in enumerate(header)
            }
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        # A truncated or outdated file is worth nothing and worth no more thought.
        return {}


def _write_audit_cache(
    path: Path, key: str, measured: dict[str, tuple[PartAudit, PartFit]]
) -> None:
    arrays: dict[str, np.ndarray] = {}
    header = []
    for index, (audit, fit) in enumerate(measured.values()):
        record = asdict(audit)
        record.pop("source")
        header.append(record)
        arrays[f"{index}.bulge"] = fit.bulge_m
        arrays[f"{index}.gap"] = fit.gap_m
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as stream:
        np.savez_compressed(stream, key=key, header=json.dumps(header), **arrays)
    temporary.replace(path)


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


def _start_meshcat(label: str):
    """A Meshcat server announced with a URL that also works from the Windows browser."""

    from pydrake.geometry import Meshcat

    from .meshcat_ui import announce_viewer, viewer_params

    meshcat = Meshcat(viewer_params(show_stats_plot=True))
    announce_viewer(label, meshcat)
    return meshcat


def run_hull_viewer(parts: Sequence[PartGeometry]) -> None:
    """Show one part at a time with its hulls drawn over the CAD mesh."""

    import time

    from pydrake.geometry import Rgba

    from .meshcat_ui import print_view_help

    meshcat = _start_meshcat("Hull audit viewer")
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
    print_view_help()
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
            hull_style = (hull_style + 1) % 3
            meshcat.DeleteButton(hull_button)
            hull_button = (HULLS_ON, HULLS_WIRE, HULLS_OFF)[hull_style]
            meshcat.AddButton(hull_button)
            # Relabelling makes a new button, whose count starts at zero again; carrying
            # the old count over re-fires the toggle on the next poll.
            hull_clicks = 0
            changed = True
        if new_source != source_clicks:
            source_visible = not source_visible
            meshcat.DeleteButton(source_button)
            source_button = SOURCE_ON if source_visible else SOURCE_OFF
            meshcat.AddButton(source_button)
            source_clicks = 0
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


def run_assembly_viewer(parts: Sequence[PartGeometry], *, bulge_scale_mm: float) -> None:
    """Draw every audited part where it actually sits, hulls layered over the CAD mesh.

    The one-at-a-time viewer answers "how bad is this part"; this one answers "which
    parts are bad", which is the question a decomposition-settings pass starts from.
    """

    import time

    meshcat = _start_meshcat("Assembly hull viewer")

    hulls = sum(part.audit.hull_count for part in parts)
    print(f"Uploading {len(parts)} parts and {hulls} hulls; this takes a moment.")
    for index, part in enumerate(parts):
        _upload_part(meshcat, f"/assembly/part{index:04d}", part, bulge_scale_mm)

    meshcat.AddSlider(FOCUS_LABEL, 0.0, float(len(parts) - 1), 1.0, 0.0)
    meshcat.AddSlider(WORST_LABEL, 1.0, float(len(parts)), 1.0, float(len(parts)))
    meshcat.AddButton("Stop viewer", "Escape")
    hull_button, source_button = HULLS_PIECE, SOURCE_ON
    meshcat.AddButton(hull_button)
    meshcat.AddButton(source_button)

    print()
    print("Every part is drawn at its assembly position, worst fit first by index.")
    print("Grey is the CAD mesh; the translucent shells over it are the hulls Drake sees.")
    print(
        "Piece colours separate one hull from the next; bulge shading recolours them "
        f"grey where they lie on the CAD surface and red at {bulge_scale_mm:.1f} mm of "
        "outward bulge, which is material Drake will collide with that is not there."
    )
    print("'Show worst N parts' hides the good parts and leaves the bad ones in place.")
    print("'Focus part index' flies the camera to one part and prints which it is.")

    _frame_assembly(meshcat, parts)
    hull_style = 0
    source_visible = True
    shown = len(parts)
    # Starts matched to the slider so the opening view stays wide, not on one part.
    focused = 0
    hull_clicks = 0
    source_clicks = 0
    while meshcat.GetButtonClicks("Stop viewer") == 0:
        new_hull = meshcat.GetButtonClicks(hull_button)
        new_source = meshcat.GetButtonClicks(source_button)
        restyle = False
        if new_hull != hull_clicks:
            hull_style = (hull_style + 1) % 3
            meshcat.DeleteButton(hull_button)
            hull_button = (HULLS_PIECE, HULLS_BULGE, HULLS_HIDDEN)[hull_style]
            meshcat.AddButton(hull_button)
            # Relabelling makes a new button, whose count starts at zero again; carrying
            # the old count over re-fires the toggle on the next poll.
            hull_clicks = 0
            restyle = True
        if new_source != source_clicks:
            source_visible = not source_visible
            meshcat.DeleteButton(source_button)
            source_button = SOURCE_ON if source_visible else SOURCE_OFF
            meshcat.AddButton(source_button)
            source_clicks = 0
            restyle = True
        if restyle:
            for index in range(shown):
                root = f"/assembly/part{index:04d}"
                meshcat.SetProperty(f"{root}/pieces", "visible", hull_style == 0)
                meshcat.SetProperty(f"{root}/bulge", "visible", hull_style == 1)
                meshcat.SetProperty(f"{root}/mesh", "visible", source_visible)

        wanted = min(max(int(round(meshcat.GetSliderValue(WORST_LABEL))), 1), len(parts))
        if wanted != shown:
            for index in range(min(wanted, shown), max(wanted, shown)):
                meshcat.SetProperty(f"/assembly/part{index:04d}", "visible", index < wanted)
            shown = wanted

        index = min(max(int(round(meshcat.GetSliderValue(FOCUS_LABEL))), 0), len(parts) - 1)
        if index != focused:
            focused = index
            _frame_camera(meshcat, parts[index])
            print(_describe(index, parts[index].audit))
        time.sleep(0.05)


def run_tour_viewer(parts: Sequence[PartGeometry], *, bulge_scale_mm: float) -> None:
    """Walk the least accurate parts one at a time, advancing on a click.

    The other two viewers ask which part you want to see; this one answers that from the
    audit itself, so the review needs no index and no slider, only Next.
    """

    import time

    from .meshcat_ui import print_view_help

    meshcat = _start_meshcat("Hull tour viewer")
    print(f"Uploading the {len(parts)} least accurate parts")
    for index, part in enumerate(parts):
        root = f"/tour/part{index:03d}"
        _upload_part(meshcat, root, part, bulge_scale_mm)
        meshcat.SetProperty(root, "visible", False)

    meshcat.AddButton(TOUR_NEXT, "ArrowRight")
    meshcat.AddButton(TOUR_PREVIOUS, "ArrowLeft")
    hull_button, source_button = HULLS_PIECE, SOURCE_ON
    meshcat.AddButton(hull_button)
    meshcat.AddButton(source_button)
    meshcat.AddButton("Stop viewer", "Escape")

    print()
    print(f"The {len(parts)} worst-fitting parts, worst first, one per click.")
    print("Grey is the CAD mesh; the translucent shells over it are the hulls Drake sees.")
    print("Next and Previous step through them and wrap round; the arrow keys do the same.")
    print("The panel repeats the audited numbers for the part on screen.")
    print_view_help()
    print("Press Escape in Meshcat or Ctrl-C here to stop.")

    hull_style = 0
    source_visible = True
    current = -1
    hull_clicks = 0
    source_clicks = 0
    readout: list[str] = []
    while meshcat.GetButtonClicks("Stop viewer") == 0:
        # Derived from the counters rather than tracked, so a click between polls is never
        # lost and either end of the tour wraps on its own.
        step = meshcat.GetButtonClicks(TOUR_NEXT) - meshcat.GetButtonClicks(TOUR_PREVIOUS)
        index = step % len(parts)
        new_hull = meshcat.GetButtonClicks(hull_button)
        new_source = meshcat.GetButtonClicks(source_button)
        changed = False
        if index != current:
            if current >= 0:
                meshcat.SetProperty(f"/tour/part{current:03d}", "visible", False)
            current = index
            meshcat.SetProperty(f"/tour/part{current:03d}", "visible", True)
            _frame_camera(meshcat, parts[current])
            print(_describe(current, parts[current].audit))
            changed = True
        if new_hull != hull_clicks:
            hull_style = (hull_style + 1) % 3
            meshcat.DeleteButton(hull_button)
            hull_button = (HULLS_PIECE, HULLS_BULGE, HULLS_HIDDEN)[hull_style]
            meshcat.AddButton(hull_button)
            hull_clicks = 0
            changed = True
        if new_source != source_clicks:
            source_visible = not source_visible
            meshcat.DeleteButton(source_button)
            source_button = SOURCE_ON if source_visible else SOURCE_OFF
            meshcat.AddButton(source_button)
            source_clicks = 0
            changed = True
        if changed:
            root = f"/tour/part{current:03d}"
            meshcat.SetProperty(f"{root}/pieces", "visible", hull_style == 0)
            meshcat.SetProperty(f"{root}/bulge", "visible", hull_style == 1)
            meshcat.SetProperty(f"{root}/mesh", "visible", source_visible)
            # Republished after any change so the numbers stay under the buttons rather
            # than above whichever one a toggle just re-added.
            readout = _set_readout(
                meshcat, readout, tour_labels(current, len(parts), parts[current].audit)
            )
        time.sleep(0.05)


def tour_labels(index: int, total: int, audit: PartAudit) -> list[str]:
    """The audited numbers for one part, phrased for the panel rather than the table."""

    # No apostrophes: Drake builds each control's JS callback by pasting the name into a
    # single-quoted string literal and eval-ing it, so a quote drops the control.
    return [
        f"Part {index + 1} of {total}: {audit.label}",
        f"volume {audit.volume_ratio:.2f}x CAD, {audit.hull_count} hulls",
        f"bulge {audit.max_bulge_mm:.2f} mm of material that is not there",
        f"gap {audit.max_gap_mm:.3f} mm of material Drake cannot see",
    ]


def _set_readout(meshcat, previous: Sequence[str], labels: Sequence[str]) -> list[str]:
    """Republish text as buttons, which is the only text Meshcat can show."""

    for name in previous:
        meshcat.DeleteButton(name)
    for name in labels:
        meshcat.AddButton(name)
    return list(labels)


def _upload_part(meshcat, root: str, part: PartGeometry, bulge_scale_mm: float) -> None:
    """Both colourings at once: swapping them later is a visibility flip, not a re-upload."""

    from pydrake.geometry import Rgba

    meshcat.SetTriangleMesh(
        f"{root}/mesh", _columns(part.vertices), _indices(part.faces), Rgba(*SOURCE_RGBA)
    )
    start = 0
    for hull_index, hull in enumerate(part.hulls):
        stop = start + len(hull.vertices)
        colors = _columns(_bulge_colors(part.fit.bulge_m[start:stop], bulge_scale_mm))
        start = stop
        vertices, faces = _columns(hull.vertices), _indices(hull.faces)
        red, green, blue = HULL_RGBA[hull_index % len(HULL_RGBA)]
        meshcat.SetTriangleMesh(
            f"{root}/pieces/{hull_index:03d}",
            vertices,
            faces,
            Rgba(red, green, blue, HULL_ALPHA),
        )
        meshcat.SetTriangleColorMesh(f"{root}/bulge/{hull_index:03d}", vertices, faces, colors)
    meshcat.SetProperty(f"{root}/bulge", "visible", False)


def _bulge_colors(bulge_m: np.ndarray, scale_mm: float) -> np.ndarray:
    if len(bulge_m) == 0:
        return np.zeros((0, 3))
    fraction = np.clip(bulge_m * MM_PER_M / max(scale_mm, 1e-6), 0.0, 1.0)
    stops = np.asarray(BULGE_RAMP_RGB)
    positions = np.asarray(BULGE_RAMP_STOPS)
    return np.stack(
        [np.interp(fraction, positions, stops[:, channel]) for channel in range(3)], axis=1
    )


def _frame_assembly(meshcat, parts: Sequence[PartGeometry]) -> None:
    lower = np.min([part.vertices.min(axis=0) for part in parts], axis=0)
    upper = np.max([part.vertices.max(axis=0) for part in parts], axis=0)
    center = (lower + upper) / 2.0
    span = max(float(np.linalg.norm(upper - lower)), 1e-3)
    _look_at(meshcat, center + np.array([0.5, -0.7, 0.4]) * span, center)


def _look_at(meshcat, eye: np.ndarray, target: np.ndarray) -> None:
    # pydrake's stub gives SetCameraPose a malformed Eigen shape; lists convert at runtime.
    meshcat.SetCameraPose(eye.tolist(), target.tolist())  # pyright: ignore[reportArgumentType]


def _frame_camera(meshcat, part: PartGeometry) -> None:
    lower, upper = part.vertices.min(axis=0), part.vertices.max(axis=0)
    center = (lower + upper) / 2.0
    span = max(float(np.linalg.norm(upper - lower)), 1e-3)
    _look_at(meshcat, center + np.array([0.7, -0.9, 0.6]) * span, center)


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
    parser.add_argument(
        "--assembly",
        action="store_true",
        help="Show every audited part at its assembly position, hulls over the CAD mesh",
    )
    parser.add_argument(
        "--tour",
        action="store_true",
        help="Step through the least accurate parts in Meshcat, one per click",
    )
    parser.add_argument(
        "--tour-count",
        type=int,
        default=TOUR_DEFAULT_COUNT,
        help="Parts in the tour, worst fit first",
    )
    parser.add_argument(
        "--bulge-scale-mm",
        type=float,
        default=DEFAULT_BULGE_SCALE_MM,
        help="Outward bulge that saturates the red end of the assembly viewer's colour ramp",
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-measure every part instead of reusing the cached distances",
    )
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
        refresh=args.refresh,
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
    if args.tour:
        run_tour_viewer(parts[: max(args.tour_count, 1)], bulge_scale_mm=args.bulge_scale_mm)
    elif args.assembly:
        run_assembly_viewer(parts, bulge_scale_mm=args.bulge_scale_mm)
    elif args.view:
        run_hull_viewer(parts[: args.view_limit])


if __name__ == "__main__":
    main()
