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
SOURCE = ROOT / "cad/DSG-000095835.stp"
MANIFEST = Path(__file__).with_name("manifest.json")
CACHE = ROOT / ".cache/twin_lab/95835-inspect"
SCHEMA = 1


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
    CACHE.mkdir(parents=True, exist_ok=True)
    stats = {}
    for ref, occurrence in leaf_occurrences(roots).items():
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


if __name__ == "__main__":
    result = prepare_geometry()
    print(f"Cached {len(result)} STEP leaf occurrences in {CACHE}.")
