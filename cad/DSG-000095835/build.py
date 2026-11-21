"""Build and view the offline DSG-000095835 assembly without changing shared tooling.

The local review describes a branching tree and solid selections within STEP leaves.
Those two features are not representable in the older stage-inventory schema.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import yaml
from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.BRepGProp import BRepGProp
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.BRepTools import BRepTools
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec
from OCP.GProp import GProp_GProps
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDocStd import TDocStd_Document
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED, TopAbs_SOLID
from OCP.TopExp import TopExp, TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS, TopoDS_Compound, TopoDS_Shape
from OCP.TopTools import TopTools_IndexedMapOfShape
from OCP.XCAFDoc import XCAFDoc_DocumentTool

from twin_lab.cad_geometry import OccurrenceShape, write_group_obj
from twin_lab.convex_collision import part_settings_from_config
from twin_lab.paths import CACHE_ROOT, EXPORT_ROOT
from twin_lab.sdf_compiler import (
    JointSpec,
    LinkSpec,
    _convert_meshes,
    _write_joint_metadata,
    _write_matlab_loader,
    _write_sdf,
)

HERE = Path(__file__).resolve().parent
RECIPE = HERE / "reviews" / "assembly.yaml"
CACHE = CACHE_ROOT / "95835-inspect"
MESHES = CACHE_ROOT / "DSG-000095835" / "meshes"
# Bump when the STEP-coloured visual mesh format changes.
VISUAL_SCHEMA = 1
EMPTY_GEOMETRY = "Empty geometry in source STEP"


def select_solids(shape: TopoDS_Shape, ref: str, solids: list[int] | None) -> TopoDS_Shape:
    if solids is None:
        return shape
    if not solids or len(set(solids)) != len(solids):
        raise ValueError(f"Empty or duplicate solid selection: {ref} {solids}")
    result = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(result)
    explorer = TopExp_Explorer(shape, TopAbs_SOLID)
    index = 0
    selected = set()
    while explorer.More():
        index += 1
        if index in solids:
            builder.Add(result, explorer.Current())
            selected.add(index)
        explorer.Next()
    if selected != set(solids):
        raise ValueError(f"Unknown solid indices in {ref}: {set(solids) - selected}")
    return result


def mask_shape(spec: dict) -> TopoDS_Shape:
    if spec["kind"] == "box":
        return BRepPrimAPI_MakeBox(gp_Pnt(*spec["min_mm"]), gp_Pnt(*spec["max_mm"])).Shape()
    if spec["kind"] == "cylinder":
        axis = gp_Ax2(gp_Pnt(*spec["origin_mm"]), gp_Dir(*spec["axis_xyz"]))
        return BRepPrimAPI_MakeCylinder(axis, spec["radius_mm"], spec["length_mm"]).Shape()
    if spec["kind"] in {"intersection", "difference", "union"}:
        operands = [mask_shape(item) for item in spec["operands"]]
        operation = {
            "intersection": BRepAlgoAPI_Common,
            "difference": BRepAlgoAPI_Cut,
            "union": BRepAlgoAPI_Fuse,
        }[spec["kind"]]
        result = operands[0]
        for operand in operands[1:]:
            result = operation(result, operand).Shape()
        return result
    raise ValueError(f"Unknown mask kind: {spec['kind']}")


def _placement(
    stats: dict, ref: str, review: dict | None = None, region: str | None = None
) -> gp_Trsf:
    matrix = np.array(stats[ref]["transform"])
    transform = gp_Trsf()
    transform.SetValues(*matrix[:3, :].flatten().tolist())
    offset = (review or {}).get("stage_splits", {}).get(ref, {}).get("moving_offset_mm")
    if region == "moving" and offset:
        # The STEP can place a payload away from the carriage modelled in a fused stage.
        shift = gp_Trsf()
        shift.SetTranslation(gp_Vec(*offset))
        transform = transform.Multiplied(shift)
    return transform


def expand_stage_splits(review: dict, templates: dict) -> dict:
    """Resolve each reviewed split to its template, keeping any per-stage carriage offset."""
    splits = {}
    for ref, entry in review["stage_splits"].items():
        if isinstance(entry, str):
            splits[ref] = templates[entry]
        else:
            extra = {key: value for key, value in entry.items() if key != "template"}
            splits[ref] = {**templates[entry["template"]], **extra}
    return splits


def _region_solids(shape: TopoDS_Shape, ref: str, region: str, review: dict):
    """Split a local fused stage body; return its source solids, the Boolean, and the kept half."""
    split = review["stage_splits"][ref]
    selected = select_solids(shape, ref, split["source_solids"])
    mask = mask_shape(split["moving_mask"])
    operation = BRepAlgoAPI_Common if region == "moving" else BRepAlgoAPI_Cut
    cut = operation(selected, mask)
    if not cut.IsDone():
        raise ValueError(f"Failed to split {ref} ({region})")
    # The imported swivel contains inverted screw-hole fragments. Keep physical
    # positive-volume solids and prune disconnected fastening/detail fragments.
    clean = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(clean)
    explorer = TopExp_Explorer(cut.Shape(), TopAbs_SOLID)
    count = 0
    while explorer.More():
        properties = GProp_GProps()
        BRepGProp.VolumeProperties_s(explorer.Current(), properties)
        if properties.Mass() >= 100.0:
            builder.Add(clean, explorer.Current())
            count += 1
        explorer.Next()
    if not count:
        raise ValueError(f"Split {ref} ({region}) has no physical solids")
    return selected, cut, clean


def read_shape(part: str | dict, review: dict, stats: dict) -> TopoDS_Shape:
    ref = part if isinstance(part, str) else part["ref"]
    region = None if isinstance(part, str) else part.get("region")
    shape = TopoDS_Shape()
    frame = "local" if region else "placed"
    if not BRepTools.Read_s(shape, str(CACHE / f"{ref}-{frame}.brep"), BRep_Builder()):
        raise ValueError(f"Cannot read cached shape {ref}")
    if not region:
        return select_solids(shape, ref, None if isinstance(part, str) else part.get("solids"))
    _, _, clean = _region_solids(shape, ref, region, review)
    return BRepBuilderAPI_Transform(clean, _placement(stats, ref, review, region), True).Shape()


def _faces(shape: TopoDS_Shape) -> TopTools_IndexedMapOfShape:
    faces = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, faces)
    return faces


def colored_shape(
    part: str | dict, review: dict, stats: dict, leaf: dict
) -> tuple[TopoDS_Shape, list[tuple[float, ...] | None]]:
    """Place a selection from its local BRep and carry each STEP face colour onto it.

    Colours are listed in ``TopExp.MapShapes`` face order of the returned shape. Boolean
    history colours split pieces of a source face; faces the split mask creates get none.
    """
    ref = part if isinstance(part, str) else part["ref"]
    region = None if isinstance(part, str) else part.get("region")
    local = TopoDS_Shape()
    if not BRepTools.Read_s(local, str(CACHE / f"{ref}-local.brep"), BRep_Builder()):
        raise ValueError(f"Cannot read cached shape {ref}")
    source = _faces(local)
    if source.Extent() != len(leaf["faces"]):
        raise ValueError(f"STEP colours do not match the cached faces of {ref}")
    if region:
        _, operation, kept = _region_solids(local, ref, region, review)
    else:
        operation = None
        kept = select_solids(local, ref, None if isinstance(part, str) else part.get("solids"))
    kept_faces = _faces(kept)
    transformer = BRepBuilderAPI_Transform(kept, _placement(stats, ref, review, region), True)
    placed = transformer.Shape()
    placed_faces = _faces(placed)
    colors: list[tuple[float, ...] | None] = [None] * placed_faces.Extent()
    for index in range(1, source.Extent() + 1):
        palette_index = leaf["faces"][index - 1]
        face = source.FindKey(index)
        if palette_index < 0 or (operation is not None and operation.IsDeleted(face)):
            continue
        pieces = [face] if operation is None else (list(operation.Modified(face)) or [face])
        for piece in pieces:
            if kept_faces.FindIndex(piece):
                target = placed_faces.FindIndex(transformer.ModifiedShape(piece))
                if target:
                    colors[target - 1] = tuple(leaf["palette"][palette_index])
    return placed, colors


def write_colored_obj(
    shape: TopoDS_Shape,
    colors: list[tuple[float, ...] | None],
    default: tuple[float, ...],
    ref: str,
    output: Path,
    *,
    linear_deflection_mm: float,
) -> list[float]:
    """Write placed geometry as OBJ+MTL with one material per colour; return the main colour."""
    BRepMesh_IncrementalMesh(shape, linear_deflection_mm, False, 0.5, True).Perform()
    faces = _faces(shape)
    vertices: list[tuple[float, float, float]] = []
    groups: dict[tuple[float, ...], list[tuple[int, int, int]]] = {}
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        face = TopoDS.Face_s(explorer.Current())  # pyright: ignore[reportAttributeAccessIssue]
        location = TopLoc_Location()
        triangulation = BRep_Tool.Triangulation_s(face, location)
        if triangulation is not None:
            offset = len(vertices)
            transform = location.Transformation()
            for index in range(1, triangulation.NbNodes() + 1):
                point = triangulation.Node(index).Transformed(transform)
                vertices.append((point.X() * 0.001, point.Y() * 0.001, point.Z() * 0.001))
            triangles = groups.setdefault(colors[faces.FindIndex(face) - 1] or default, [])
            for index in range(1, triangulation.NbTriangles() + 1):
                n1, n2, n3 = (triangulation.Triangle(index).Value(i) for i in (1, 2, 3))
                if face.Orientation() == TopAbs_REVERSED:
                    n1, n2, n3 = n3, n2, n1
                triangles.append((offset + n1, offset + n2, offset + n3))
        explorer.Next()
    groups = {color: triangles for color, triangles in groups.items() if triangles}
    if not groups:
        raise ValueError(f"Selection produced no mesh triangles: {output.stem}")
    points = np.array(vertices)
    areas = {}
    for color, triangles in groups.items():
        corners = points[np.array(triangles) - 1]
        edges = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
        areas[color] = float(np.linalg.norm(edges, axis=1).sum())
    material = output.with_suffix(".mtl")
    lines = [f"mtllib {material.name}"]
    lines.extend(f"v {x:.9g} {y:.9g} {z:.9g}" for x, y, z in vertices)
    lines.append(f"o {ref}")
    materials = []
    for number, (color, triangles) in enumerate(groups.items()):
        lines.append(f"usemtl c{number}")
        lines.extend(f"f {a} {b} {c}" for a, b, c in triangles)
        red, green, blue, alpha = color
        materials.append(f"newmtl c{number}\nKd {red:.4f} {green:.4f} {blue:.4f}\nd {alpha:.4f}\n")
    output.write_text("\n".join(lines) + "\n", encoding="ascii")
    material.write_text("".join(materials), encoding="ascii")
    return list(max(areas, key=areas.__getitem__))


def step_visual(
    part: str | dict, review: dict, stats: dict, leaf: dict, fallback: list[float],
    mesh: Path, mesh_key: str, *, rebuild: bool,
) -> tuple[list[float], Path]:
    """Cache a STEP-coloured visual for one selection beside its collision source mesh."""
    ref = part if isinstance(part, str) else part["ref"]
    visual = mesh.with_suffix(".visual.obj")
    record = mesh.with_suffix(".visual.json")
    key = hashlib.sha256(
        json.dumps([VISUAL_SCHEMA, mesh_key, leaf, fallback], sort_keys=True).encode()
    ).hexdigest()
    if not rebuild and visual.exists() and visual.with_suffix(".mtl").exists() and record.exists():
        cached = json.loads(record.read_text())
        if cached.get("key") == key:
            return cached["rgba"], visual
    shape, colors = colored_shape(part, review, stats, leaf)
    # Faces the STEP leaves uncoloured, and faces cut by a split, take the part's usual colour.
    counts = {}
    for index in leaf["faces"]:
        if index >= 0:
            counts[index] = counts.get(index, 0) + 1
    default = tuple(fallback)
    if counts:
        default = tuple(leaf["palette"][max(counts, key=counts.__getitem__)])
    rgba = write_colored_obj(
        shape, colors, default, ref, visual,
        linear_deflection_mm=float(review.get("linear_deflection_mm", 0.5)),
    )
    record.write_text(json.dumps({"key": key, "rgba": rgba}) + "\n")
    return rgba, visual


def validate_review(review: dict, stats: dict) -> None:
    """Reject duplicate geometry ownership, missing parts, and disconnected links."""
    bodies = review["bodies"]
    if "assembly_base" not in bodies:
        raise ValueError("An assembly_base body is required")
    owners = {}
    for body, spec in bodies.items():
        for part in spec["parts"]:
            ref = part if isinstance(part, str) else part["ref"]
            if ref not in stats:
                raise ValueError(f"Unknown CAD reference: {ref}")
            region = None if isinstance(part, str) else part.get("region")
            if region is not None and region not in {"fixed", "moving"}:
                raise ValueError(f"Unknown region {region}")
            indices = (
                list(range(1, len(stats[ref]["local"]["solids"]) + 1)) or [0]
                if isinstance(part, str)
                else review["stage_splits"][ref]["source_solids"]
                if region
                else part["solids"]
            )
            for index in indices:
                key = (ref, index, region)
                conflicts = [
                    k
                    for k in owners
                    if k[:2] == key[:2] and (k[2] == region or k[2] is None or region is None)
                ]
                if conflicts:
                    raise ValueError(f"{key} belongs to both {owners[conflicts[0]]} and {body}")
                owners[key] = body
    retained = {key[0] for key in owners}
    omitted_list = [ref for refs in review["omitted_occurrences"].values() for ref in refs]
    omitted = set(omitted_list)
    if len(omitted) != len(omitted_list) or retained & omitted:
        raise ValueError("Retained/omitted occurrence assignments overlap")
    if retained | omitted != set(stats):
        raise ValueError("Every source leaf must be retained or explicitly omitted")
    # Re-exports can fill in previously empty parts; a stale entry would silently hide them.
    empty = {ref for ref, item in stats.items() if not item["local"]["solids"]}
    listed_empty = set(review["omitted_occurrences"].get(EMPTY_GEOMETRY, []))
    if listed_empty != empty:
        raise ValueError(
            f"{EMPTY_GEOMETRY!r} must list exactly the leaves without solids; "
            f"has solids: {sorted(listed_empty - empty)}, unlisted: {sorted(empty - listed_empty)}"
        )
    for ref in review["stage_splits"]:
        regions = {key[2] for key in owners if key[0] == ref and key[2] is not None}
        if regions != {"fixed", "moving"}:
            raise ValueError(f"Both halves of split {ref} must be assigned")
    reached = {"assembly_base"}
    names = set()
    for joint in review["joints"]:
        if joint["name"] in names or joint["name"] in bodies:
            raise ValueError(f"Joint name must be unique across links and joints: {joint['name']}")
        names.add(joint["name"])
        if joint["parent"] not in reached or joint["child"] in reached:
            raise ValueError(f"Joint tree must be ordered and acyclic: {joint['name']}")
        if joint["child"] not in bodies:
            raise ValueError(f"Unknown child {joint['child']}")
        reached.add(joint["child"])
        axis = np.asarray(joint["axis_xyz"], dtype=float)
        if (
            axis.shape != (3,)
            or not np.isfinite(axis).all()
            or not np.isclose(np.linalg.norm(axis), 1.0, atol=1e-6)
        ):
            raise ValueError(f"Invalid axis for {joint['name']}")
        low, high = joint["limits"]
        if not np.isfinite([low, high, *joint["origin_m"]]).all() or not low < high:
            raise ValueError(f"Invalid limits/frame for {joint['name']}")
        if not low <= joint.get("home", 0.0) <= high or not low <= 0 <= high:
            raise ValueError(f"CAD/home pose outside limits: {joint['name']}")
    from controls import follower_position

    joints = {joint["name"]: joint for joint in review["joints"]}
    for joint in joints.values():
        if "follows" not in joint:
            continue
        leader = joints.get(joint["follows"]["joint"])
        rule = {key: value for key, value in joint["follows"].items() if key != "joint"}
        if leader is None or "follows" in leader or len(rule) != 1:
            raise ValueError(f"{joint['name']} must follow an independent joint by one rule")
        if "ratio" in rule:
            ratio = float(rule["ratio"])
            if not np.isfinite(ratio) or ratio == 0.0:
                raise ValueError(f"{joint['name']} must follow its leader by a finite ratio")
        elif "scissor" in rule:
            arm, rise = float(rule["scissor"]["arm_m"]), float(rule["scissor"]["rise_m"])
            reach = [(rise + q) / arm for q in leader["limits"]]
            if rule["scissor"]["output"] not in {"angle", "slide"} or not (
                arm > 0.0 and all(0.0 < value < 1.0 for value in reach)
            ):
                raise ValueError(f"{joint['name']} must follow a scissor that stays unfolded")
        else:
            raise ValueError(f"{joint['name']} must follow its leader by a ratio or scissor rule")
        # Both rules are monotonic, so a follower's travel is its leader's end positions mapped,
        # and neither joint clamps the other. The SDF rejects positions even 1e-13 past a limit,
        # so the mapped ends must also fall inside the follower's limits.
        ends = sorted(follower_position(rule, q) for q in leader["limits"])
        low, high = joint["limits"]
        if not np.allclose(ends, joint["limits"], rtol=0.0, atol=1e-9) or not (
            low <= ends[0] and ends[1] <= high
        ):
            raise ValueError(f"{joint['name']} limits must be {ends}, {leader['name']}'s mapped")
    if reached != set(bodies):
        raise ValueError(f"Disconnected bodies: {set(bodies) - reached}")


def build(
    *, collision: str = "none", workers: int | None = None, rebuild: bool = False,
    refinement_run: Path | None = None, output_dir: Path | None = None,
) -> Path:
    from cache_geometry import prepare_geometry

    default_name = "DSG-000095835" if collision == "none" else "DSG-000095835.collision"
    output = (output_dir or EXPORT_ROOT / (
        "DSG-000095835.candidate" if refinement_run is not None else default_name
    )).resolve()
    if refinement_run is not None:
        if collision != "convex" or rebuild:
            raise ValueError("Refinement candidates require convex mode without --rebuild")
        if output in {(EXPORT_ROOT / name).resolve() for name in (
            "DSG-000095835", "DSG-000095835.collision",
        )} or output.exists():
            raise ValueError("Refinement candidates require a new, separate output directory")
    prepare_geometry()
    recipe_bytes = RECIPE.read_bytes()
    review = yaml.safe_load(recipe_bytes)
    template_bytes = (RECIPE.parent / review["split_templates"]).read_bytes()
    templates = yaml.safe_load(template_bytes)
    review["stage_splits"] = expand_stage_splits(review, templates)
    stats = json.loads((CACHE / "stats.json").read_text())
    if json.loads((CACHE / "source-stamp.json").read_text())["sha256"] != review["source_sha256"]:
        raise ValueError("STEP revision differs from this review; re-review CAD references first")
    validate_review(review, stats)
    MESHES.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    (output / "meshes").mkdir(exist_ok=True)
    # Every body mesh is keyed to its exact solid selection and source revision.
    source_key = (CACHE / "source-stamp.json").read_bytes()
    document = TDocStd_Document(TCollection_ExtendedString("95835-export"))
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    # STEP presentation colours go into visual-only OBJ+MTL meshes, so the collision source
    # meshes, and the convex decompositions keyed to their bytes, are unchanged.
    step_colors = review.get("visual_colors") == "step"
    if step_colors:
        from cache_geometry import prepare_colors

        leaf_colors = prepare_colors()
    colored_visuals: dict[Path, Path] = {}
    links = []
    for name, spec in review["bodies"].items():
        link = LinkSpec(name)
        # One mesh per selected leaf keeps fast hull checks from filling entire stacks.
        for part in spec["parts"]:
            ref = part if isinstance(part, str) else part["ref"]
            solids = None if isinstance(part, str) else part.get("solids")
            region = None if isinstance(part, str) else part.get("region")
            label = ref if solids is None else f"{ref}_s{'_'.join(map(str, solids))}"
            if region:
                label = f"{ref}_{region}"
            mesh = MESHES / f"{name}_{label}.obj"
            key = hashlib.sha256(
                source_key
                + json.dumps(
                    [
                        part,
                        review.get("linear_deflection_mm", 0.5),
                        review.get("stage_splits", {}).get(ref),
                    ],
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            stamp = mesh.with_suffix(".key")
            if rebuild or not mesh.exists() or not stamp.exists() or stamp.read_text() != key:
                shape = read_shape(part, review, stats)
                cad_label = shape_tool.AddShape(shape, False)
                TDataStd_Name.Set_s(cad_label, TCollection_ExtendedString(label))
                write_group_obj(
                    [OccurrenceShape(ref, label, cad_label, TopLoc_Location())],
                    mesh,
                    linear_deflection_mm=float(review.get("linear_deflection_mm", 0.5)),
                )
                stamp.write_text(key)
            color = review.get(
                "visual_rgba",
                spec.get("part_colors", {}).get(ref, spec.get("rgba", [0.62, 0.66, 0.72, 1.0])),
            )
            if step_colors:
                color, colored_visuals[mesh] = step_visual(
                    part, review, stats, leaf_colors[ref], color, mesh, key, rebuild=rebuild
                )
            link.meshes.append((label, mesh, color))
        links.append(link)
        print(f"  {name}: {len(link.meshes)} CAD selections", flush=True)
    joints = [
        JointSpec(
            name=j["name"],
            stack=j.get("stack", j["name"]),
            reference=j["stage_ref"],
            joint_type=j["type"],
            parent=j["parent"],
            child=j["child"],
            axis=j["axis_xyz"],
            origin=j["origin_m"],
            lower=j["limits"][0],
            upper=j["limits"][1],
            logical_home=0.0,
            reviewed_home=j.get("home", 0.0),
        )
        for j in review["joints"]
    ]
    supplied_parts = None
    if refinement_run is not None:
        from refine_hulls import candidate_parts, write_json

        supplied_parts, evidence = candidate_parts(
            refinement_run,
            {source for link in links for _, source, _ in link.meshes},
            recipe_bytes,
        )
        write_json(output / "refinement.json", {
            "run": str(refinement_run.resolve()), "selections": evidence,
            "improved_selections": sum(item["improved"] for item in evidence),
        })
    visual, stl, collision_meshes = _convert_meshes(
        links,
        output / "meshes",
        RECIPE,
        include_collision_obj=collision != "none",
        collision_mode=collision if collision != "none" else "hull",
        decomposition_workers=workers,
        decomposition_settings=part_settings_from_config(review.get("decomposition")),
        decomposed_parts=supplied_parts,
    )
    if collision != "none":
        missing = [str(source) for source in visual if not collision_meshes.get(source)]
        if missing:
            raise ValueError(f"Retained parts have no collision geometry: {missing}")
    # These directories contain generated meshes. Remove older recipe/mode
    # outputs so inspection and camera fitting cannot pick up stale geometry.
    emitted = {Path(uri).name for uri in [*visual.values(), *stl.values()]}
    emitted.update(Path(uri).name for pieces in collision_meshes.values() for _, uri in pieces)
    for source, colored in colored_visuals.items():
        target = output / visual[source]
        material = target.with_suffix(".mtl")
        _, body = colored.read_text(encoding="ascii").split("\n", 1)
        target.write_text(f"mtllib {material.name}\n{body}", encoding="ascii")
        shutil.copyfile(colored.with_suffix(".mtl"), material)
        emitted.add(material.name)
    for path in (output / "meshes").iterdir():
        if path.suffix in {".obj", ".stl", ".mtl"} and path.name not in emitted:
            path.unlink()
    model_name = "DSG-000095835"
    sdf = output / f"{model_name}.sdf"
    _write_sdf(
        sdf,
        model_name,
        links,
        joints,
        visual,
        collision_mesh_uris=collision_meshes,
        include_collisions=collision != "none",
        declare_convex=collision == "convex",
    )
    _write_sdf(
        output / f"{model_name}_matlab.sdf",
        model_name,
        links,
        joints,
        stl,
        collision_mesh_uris={},
        include_collisions=False,
        declare_convex=False,
    )
    _write_joint_metadata(output / "joint_metadata.csv", joints)
    _write_matlab_loader(output / "load_in_matlab.m", f"{model_name}_matlab.sdf")
    (output / "build.json").write_text(
        json.dumps(
            {
                "source_step": review["source_step"],
                "recipe_sha256": hashlib.sha256(recipe_bytes).hexdigest(),
                "split_templates_sha256": hashlib.sha256(template_bytes).hexdigest(),
                "source_key": json.loads(source_key),
                "collision_mode": collision,
                "body_count": len(links),
                "joint_count": len(joints),
                "cad_selections": sum(len(link.meshes) for link in links),
                "visual_colors": "step" if step_colors else "recipe",
            },
            indent=2,
        )
        + "\n"
    )
    print(f"SDF: {sdf}", flush=True)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--view", action="store_true", help="Open the existing slider viewer")
    parser.add_argument(
        "--collision",
        choices=["none", "hull", "convex"],
        default="convex",
        help="Convex interference checking by default; none builds a fast motion-only model",
    )
    parser.add_argument("--workers", type=int)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--refinement-run", type=Path, help="Build an isolated refined candidate")
    parser.add_argument("--output-dir", type=Path, help="Override the generated package directory")
    args = parser.parse_args()
    package = build(
        collision=args.collision, workers=args.workers, rebuild=args.rebuild,
        refinement_run=args.refinement_run, output_dir=args.output_dir,
    )
    if args.view:
        if args.collision == "none":
            from view import view

            view(package)
        else:
            from collision_view import view

            view(package)


if __name__ == "__main__":
    main()
