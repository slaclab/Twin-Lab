"""Grow convex hulls until they provably contain the parts they stand in for.

The collision model replaces every part with a handful of convex hulls, and the whole
safety argument for that substitution is that a hull is a *superset* of its part: if the
hulls are clear then the parts are clear, so the query can raise a false alarm but can
never miss a contact. Measurement says otherwise. ``slac-hull-audit`` finds mesh vertices
sitting outside their own hulls on a third of the assembly, which turns a guarantee into
an unbounded exposure - a real interference can go unreported and nothing in the pipeline
would say so.

CoACD cannot be tuned out of this; a sweep of its thresholds made the fit worse, not
better. So the fix is applied after it: measure how far each hull falls short of the mesh
it covers, then grow that hull by exactly that much. Growing is the Minkowski sum with a
cube of half-width equal to the margin, which contains the ball of the same radius, so
every point within the margin of the old hull lies inside the new one. The sum of two
convex polytopes is the convex hull of their pairwise vertex sums, which is why this
needs nothing more than eight shifted copies of the hull and a convex hull routine.

The margin is per hull, not per part: only the hull nearest an uncovered vertex has to
grow, so a part that misfits in one corner does not gain material everywhere. The
original hulls stay on disk untouched and the inflated ones are written beside them, so
the decomposition that cost hours to compute is never overwritten.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from .convex_collision import read_obj_parts
from .hull_audit import Hull, load_hull, surface_gap
from .paths import CACHE_ROOT

MM_PER_M = 1000.0
# The eight corners of the unit cube. Scaled by the margin they turn the hull into its
# own Minkowski sum with a cube, which is the smallest axis-aligned body containing the
# ball of that radius, so the growth is conservative in every direction at once.
CUBE_CORNERS = np.array(
    [(x, y, z) for x in (-1.0, 1.0) for y in (-1.0, 1.0) for z in (-1.0, 1.0)],
    dtype=np.float64,
)
# Added on top of the measured shortfall. The measurement only sees mesh vertices, and a
# triangle's interior can sit marginally further out than all three of its corners.
DEFAULT_SAFETY_MM = 0.05
# Suffix for the grown hulls, kept beside the originals rather than replacing them.
INFLATED_SUFFIX = "_inflated"


def convex_hull(vertices: np.ndarray, faces: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Convex hull of a triangle soup, by the routine Drake itself applies to a Convex."""

    from pydrake.common import MemoryFile
    from pydrake.geometry import Convex, InMemoryMesh, MeshSource

    rows = [f"v {x:.12g} {y:.12g} {z:.12g}" for x, y, z in vertices]
    rows += [f"f {a + 1} {b + 1} {c + 1}" for a, b, c in faces]
    source = MeshSource(
        InMemoryMesh(mesh_file=MemoryFile("\n".join(rows), ".obj", "inflated-hull"))
    )
    mesh = Convex(source).GetConvexHull()
    points = np.array([mesh.vertex(index) for index in range(mesh.num_vertices())])
    triangles: list[tuple[int, int, int]] = []
    for index in range(mesh.num_faces()):
        polygon = mesh.element(index)
        corners = [polygon.vertex(step) for step in range(polygon.num_vertices())]
        # Drake returns each face as one polygon; a fan off its first corner triangulates
        # it exactly, because a convex hull's faces are convex.
        triangles += [
            (corners[0], corners[step], corners[step + 1]) for step in range(1, len(corners) - 1)
        ]
    return points, np.array(triangles, dtype=np.int32)


def inflate(
    vertices: np.ndarray, faces: np.ndarray, margin_m: float
) -> tuple[np.ndarray, np.ndarray]:
    """The hull grown outward by ``margin_m`` in every direction."""

    if margin_m <= 0.0:
        return vertices, faces
    shifted = (vertices[None, :, :] + margin_m * CUBE_CORNERS[:, None, :]).reshape(-1, 3)
    strides = (np.arange(len(CUBE_CORNERS)) * len(vertices))[:, None, None]
    return convex_hull(shifted, (faces[None, :, :] + strides).reshape(-1, 3))


def hull_margins(hulls: list[Hull], vertices: np.ndarray) -> np.ndarray:
    """How far each hull has to grow to swallow the mesh vertices nearest to it."""

    margins = np.zeros(len(hulls))
    if not hulls:
        return margins
    distance, nearest = surface_gap(hulls, vertices)
    for index in range(len(hulls)):
        owned = distance[nearest == index]
        if len(owned):
            margins[index] = owned.max()
    return margins


def inflate_cache(
    cache_dir: Path, *, safety_mm: float = DEFAULT_SAFETY_MM, progress: bool = False
) -> list[tuple[str, float, float]]:
    """Grow every cached hull that falls short of its part, and record it in the manifest.

    Returns one ``(label, margin_mm, volume_growth)`` row per part that needed growing.
    """

    manifests = sorted(cache_dir.rglob("manifest.json"))
    if not manifests:
        raise FileNotFoundError(f"No decomposition manifests under {cache_dir}")
    grown: list[tuple[str, float, float]] = []
    for number, manifest_path in enumerate(manifests, start=1):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        source = Path(manifest["source"])
        if not source.exists():
            print(f"  skipped {manifest_path.parent.name}: source mesh is gone ({source})")
            continue
        entries = {str(item["part_ref"]): item for item in manifest["parts"]}
        if progress:
            print(
                f"  [{number}/{len(manifests)}] {source.stem}: {len(entries)} parts",
                flush=True,
            )
        touched = False
        for part_ref, part_vertices, _ in read_obj_parts(source):
            item = entries.get(part_ref)
            if item is None:
                continue
            # Always measure against the original hulls: re-running over an inflated
            # cache must not compound the growth it already applied.
            names = [str(name) for name in item["hulls"]]
            hulls = [load_hull(manifest_path.parent / name) for name in names]
            mesh = np.asarray(part_vertices, dtype=np.float64)
            margins = hull_margins(hulls, mesh)
            if not margins.any():
                if item.pop("inflated", None) is not None:
                    touched = True
                continue
            margins = np.where(margins > 0.0, margins + safety_mm / MM_PER_M, 0.0)
            written, before, after = [], 0.0, 0.0
            for hull, margin, name in zip(hulls, margins, names, strict=True):
                grown_vertices, grown_faces = inflate(hull.vertices, hull.faces, float(margin))
                target = manifest_path.parent / f"{Path(name).stem}{INFLATED_SUFFIX}.obj"
                _write_obj(target, grown_vertices, grown_faces)
                written.append(target.name)
                before += hull.volume
                after += _volume(grown_vertices, grown_faces)
            item["inflated"] = written
            touched = True
            grown.append(
                (
                    f"{source.stem}/{part_ref}",
                    float(margins.max()) * MM_PER_M,
                    after / before if before > 0.0 else float("inf"),
                )
            )
        if touched:
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return grown


def _volume(vertices: np.ndarray, faces: np.ndarray) -> float:
    centered = vertices - vertices.mean(axis=0)
    a, b, c = centered[faces[:, 0]], centered[faces[:, 1]], centered[faces[:, 2]]
    return abs(float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum()) / 6.0)


def _write_obj(path: Path, vertices: np.ndarray, faces: np.ndarray) -> None:
    rows = [f"v {x:.9g} {y:.9g} {z:.9g}" for x, y, z in vertices]
    rows += [f"f {a + 1} {b + 1} {c + 1}" for a, b, c in faces]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Grow cached convex hulls until they contain the parts they replace",
        epilog="Originals are kept; delete the *_inflated.obj files to undo.",
    )
    parser.add_argument(
        "cache_dir",
        type=Path,
        nargs="?",
        help="Decomposition cache directory (defaults to the only scene under the cache)",
    )
    parser.add_argument(
        "--safety-mm",
        type=float,
        default=DEFAULT_SAFETY_MM,
        help="Added to each measured shortfall (default 0.05)",
    )
    args = parser.parse_args()

    cache_dir = args.cache_dir
    if cache_dir is None:
        root = CACHE_ROOT / "convex-collision"
        scenes = sorted(path for path in root.glob("*") if path.is_dir())
        if len(scenes) != 1:
            parser.error("Name the decomposition cache directory explicitly")
        cache_dir = scenes[0]

    grown = inflate_cache(cache_dir, safety_mm=args.safety_mm, progress=True)
    if not grown:
        print("Every cached hull already contains its part; nothing to grow.")
        return
    grown.sort(key=lambda row: row[1], reverse=True)
    print(f"\nGrew {len(grown)} parts:")
    for label, margin_mm, growth in grown[:15]:
        print(f"  {label:<40} margin {margin_mm:6.3f} mm   volume x{growth:.3f}")
    margins = np.array([row[1] for row in grown])
    growths = np.array([row[2] for row in grown])
    print(
        f"\nMargin mm: median {np.median(margins):.3f}, "
        f"90th pct {np.percentile(margins, 90):.3f}, max {margins.max():.3f}"
    )
    print(
        f"Volume growth: median {np.median(growths):.3f}x, "
        f"90th pct {np.percentile(growths, 90):.3f}x, max {growths.max():.3f}x"
    )


if __name__ == "__main__":
    main()
