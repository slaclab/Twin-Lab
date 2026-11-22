"""Rebuild the assembly's disposable BRep cache from the original STEP source.

Each leaf has local and globally placed BReps. The accompanying statistics use
millimetres and zero-based solid indices; motion recipe solid indices are 1-based.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(__file__).with_name("source.stp")
MANIFEST = Path(__file__).with_name("manifest.json")
CACHE = ROOT / ".cache/twin_lab/95835-inspect"
SCHEMA = 1
COLORS_SCHEMA = 1


def source_stamp() -> dict[str, Any]:
    """Fingerprint both CAD geometry and the manifest's reference assignments."""
    stat = SOURCE.stat()
    with SOURCE.open("rb") as stream:
        source_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
    return {
        "schema": SCHEMA,
        "source": SOURCE.relative_to(ROOT).as_posix(),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": source_sha256,
        "manifest_sha256": hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
    }


def prepare_geometry(*, force: bool = False) -> dict[str, Any]:
    """Return cached geometry metadata, rebuilding if its source has changed."""
    stamp = source_stamp()
    stamp_path = CACHE / "source-stamp.json"
    stats_path = CACHE / "stats.json"
    if not force and stamp_path.exists() and stats_path.exists():
        if json.loads(stamp_path.read_text()) == stamp:
            stats = json.loads(stats_path.read_text())
            if all(
                (CACHE / f"{ref}-{frame}.brep").exists()
                for ref in stats
                for frame in ("local", "placed")
            ):
                return stats

    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepGProp import BRepGProp
    from OCP.BRepTools import BRepTools
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    from OCP.XCAFDoc import XCAFDoc_ShapeTool

    from twin_lab.cad_geometry import leaf_occurrences, placed_shape
    from twin_lab.constraints_wizard import _read_step_document

    def bounds(shape: Any) -> list[float] | None:
        box = Bnd_Box()
        BRepBndLib.Add_s(shape, box, False)
        return None if box.IsVoid() else list(box.Get())

    def describe(shape: Any) -> dict[str, Any]:
        solids = []
        explorer = TopExp_Explorer(shape, TopAbs_SOLID)
        while explorer.More():
            solid = TopoDS.Solid_s(explorer.Current())
            properties = GProp_GProps()
            BRepGProp.VolumeProperties_s(solid, properties)
            center = properties.CentreOfMass()
            solids.append(
                {
                    "index": len(solids),
                    "bounds": bounds(solid),
                    "volume": properties.Mass(),
                    "center": [center.X(), center.Y(), center.Z()],
                }
            )
            explorer.Next()
        return {"bounds": bounds(shape), "solids": solids}

    print(
        f"Importing {SOURCE.name}; first-time geometry conversion takes several minutes.",
        flush=True,
    )
    document, _, roots = _read_step_document(SOURCE)
    assert document is not None  # Owns the shape labels used below.
    manifest = json.loads(MANIFEST.read_text())
    by_ref = {item["ref"]: item for item in manifest["occurrences"]}
    leaves = leaf_occurrences(roots)
    if set(leaves) != {ref for ref in by_ref if ref.startswith("P")}:
        raise SystemExit(
            f"{MANIFEST.name} does not describe {SOURCE.name} ({len(leaves)} STEP leaves); "
            "regenerate it and migrate the review for this STEP revision."
        )
    CACHE.mkdir(parents=True, exist_ok=True)
    stats = {}
    for ref, occurrence in leaves.items():
        local = XCAFDoc_ShapeTool.GetShape_s(occurrence.label)
        placed = placed_shape(occurrence)
        BRepTools.Write_s(local, str(CACHE / f"{ref}-local.brep"))
        BRepTools.Write_s(placed, str(CACHE / f"{ref}-placed.brep"))
        transform = occurrence.global_location.Transformation()
        stats[ref] = {
            "name": by_ref[ref]["name"],
            "transform": [[transform.Value(i, j) for j in range(1, 5)] for i in range(1, 4)]
            + [[0, 0, 0, 1]],
            "local": describe(local),
            "placed": describe(placed),
        }
    stats_path.write_text(json.dumps(stats, indent=2) + "\n")
    stamp_path.write_text(json.dumps(stamp, indent=2) + "\n")
    return stats


def _srgb(linear: float) -> float:
    """Open Cascade stores colours as linear RGB; STEP, MTL and SDF consumers expect sRGB."""
    if linear <= 0.0031308:
        return 12.92 * linear
    return 1.055 * linear ** (1 / 2.4) - 0.055


def prepare_colors(*, force: bool = False) -> dict[str, Any]:
    """Return each leaf's STEP face colours, re-reading the STEP only when it changed.

    ``faces`` indexes ``palette`` (sRGB red, green, blue, alpha) in ``TopExp.MapShapes`` face
    order of the leaf's local shape, the shape cached as ``{ref}-local.brep``. -1 marks a
    face the STEP leaves uncoloured. STEP carries presentation colours, not image textures.
    """

    stamp = {**source_stamp(), "colors_schema": COLORS_SCHEMA}
    path = CACHE / "colors.json"
    if not force and path.exists():
        cached = json.loads(path.read_text())
        if cached.get("stamp") == stamp:
            return cached["leaves"]
    stats = prepare_geometry()

    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.RWMesh import RWMesh_FaceIterator
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape
    from OCP.XCAFDoc import XCAFDoc_ShapeTool
    from OCP.XCAFPrs import XCAFPrs_DocumentExplorer, XCAFPrs_DocumentExplorerFlags_None

    from twin_lab.constraints_wizard import _read_step_document

    print("Reading STEP presentation colours once for this revision.", flush=True)
    document, _, _ = _read_step_document(SOURCE)
    # The explorer resolves styles inherited from parent assemblies and instances. Its
    # depth-first leaf order matches leaf_occurrences, which the placements check below.
    explorer = XCAFPrs_DocumentExplorer(document, XCAFPrs_DocumentExplorerFlags_None)
    leaves: dict[str, Any] = {}
    while explorer.More():
        node = explorer.Current()
        if not XCAFDoc_ShapeTool.IsAssembly_s(node.RefLabel):
            ref = f"P{len(leaves) + 1:03d}"
            transform = node.Location.Transformation()
            placement = [transform.Value(i, j) for i in range(1, 4) for j in range(1, 5)]
            rows = stats.get(ref, {}).get("transform", [])[:3]
            expected = [value for row in rows for value in row]
            if len(expected) != 12 or any(
                abs(a - b) > 1e-6 for a, b in zip(placement, expected, strict=True)
            ):
                raise ValueError(f"STEP colour traversal does not match cached leaf {ref}")
            shape = XCAFDoc_ShapeTool.GetShape_s(node.RefLabel)
            faces = TopTools_IndexedMapOfShape()
            TopExp.MapShapes_s(shape, TopAbs_FACE, faces)
            indices = [-1] * faces.Extent()
            palette: dict[tuple[float, ...], int] = {}
            # The face iterator only visits triangulated faces; any resolution will do.
            BRepMesh_IncrementalMesh(shape, 1.0, False, 0.5, False).Perform()
            iterator = RWMesh_FaceIterator(node.RefLabel, shape.Location(), True, node.Style)
            while iterator.More():
                index = faces.FindIndex(iterator.Face())
                if index and iterator.HasFaceColor():
                    color = iterator.FaceColor()
                    rgb = color.GetRGB()
                    key = (
                        *(round(_srgb(value), 4) for value in (rgb.Red(), rgb.Green(), rgb.Blue())),
                        round(color.Alpha(), 4),
                    )
                    indices[index - 1] = palette.setdefault(key, len(palette))
                iterator.Next()
            leaves[ref] = {"palette": [list(key) for key in palette], "faces": indices}
        explorer.Next()
    if set(leaves) != set(stats):
        raise ValueError("STEP colour traversal does not match the cached leaf set")
    path.write_text(json.dumps({"stamp": stamp, "leaves": leaves}) + "\n")
    return leaves


if __name__ == "__main__":
    result = prepare_geometry()
    print(f"Cached {len(result)} STEP leaf occurrences in {CACHE}.")
    colors = prepare_colors()
    colored = sum(bool(leaf["palette"]) for leaf in colors.values())
    print(f"Cached STEP face colours for {colored} leaves.")
