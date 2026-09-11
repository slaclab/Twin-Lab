"""Build and view the offline DSG-000095835 assembly without changing shared tooling.

The local review describes a branching tree and solid selections within STEP leaves.
Those two features are not representable in the older stage-inventory schema.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import yaml
from OCP.BRep import BRep_Builder
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.BRepGProp import BRepGProp
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.BRepTools import BRepTools
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt, gp_Trsf
from OCP.GProp import GProp_GProps
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDocStd import TDocStd_Document
from OCP.TopAbs import TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS_Compound, TopoDS_Shape
from OCP.XCAFDoc import XCAFDoc_DocumentTool

from twin_lab.cad_geometry import OccurrenceShape, write_group_obj
from twin_lab.convex_collision import part_settings_from_config
from twin_lab.paths import CACHE_ROOT, EXPORT_ROOT, REPOSITORY_ROOT
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


def read_shape(part: str | dict, review: dict, stats: dict) -> TopoDS_Shape:
    ref = part if isinstance(part, str) else part["ref"]
    region = None if isinstance(part, str) else part.get("region")
    shape = TopoDS_Shape()
    frame = "local" if region else "placed"
    if not BRepTools.Read_s(shape, str(CACHE / f"{ref}-{frame}.brep"), BRep_Builder()):
        raise ValueError(f"Cannot read cached shape {ref}")
    if not region:
        return select_solids(shape, ref, None if isinstance(part, str) else part.get("solids"))
    split = review["stage_splits"][ref]
    shape = select_solids(shape, ref, split["source_solids"])
    mask = mask_shape(split["moving_mask"])
    operation = BRepAlgoAPI_Common if region == "moving" else BRepAlgoAPI_Cut
    cut = operation(shape, mask)
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
    matrix = np.array(stats[ref]["transform"])
    transform = gp_Trsf()
    transform.SetValues(*matrix[:3, :].flatten().tolist())
    return BRepBuilderAPI_Transform(clean, transform, True).Shape()


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
    if reached != set(bodies):
        raise ValueError(f"Disconnected bodies: {set(bodies) - reached}")


def build(*, collision: str = "none", workers: int | None = None, rebuild: bool = False) -> Path:
    from cache_geometry import prepare_geometry

    prepare_geometry()
    recipe_bytes = RECIPE.read_bytes()
    review = yaml.safe_load(recipe_bytes)
    template_bytes = (RECIPE.parent / review["split_templates"]).read_bytes()
    templates = yaml.safe_load(template_bytes)
    review["stage_splits"] = {ref: templates[key] for ref, key in review["stage_splits"].items()}
    stats = json.loads((CACHE / "stats.json").read_text())
    if json.loads((CACHE / "source-stamp.json").read_text())["sha256"] != review["source_sha256"]:
        raise ValueError("STEP revision differs from this review; re-review CAD references first")
    validate_review(review, stats)
    MESHES.mkdir(parents=True, exist_ok=True)
    output = EXPORT_ROOT / ("DSG-000095835" if collision == "none" else "DSG-000095835.collision")
    output.mkdir(parents=True, exist_ok=True)
    (output / "meshes").mkdir(exist_ok=True)
    # Every body mesh is keyed to its exact solid selection and source revision.
    source_key = (CACHE / "source-stamp.json").read_bytes()
    document = TDocStd_Document(TCollection_ExtendedString("95835-export"))
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
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
    visual, stl, collision_meshes = _convert_meshes(
        links,
        output / "meshes",
        RECIPE,
        include_collision_obj=collision != "none",
        collision_mode=collision if collision != "none" else "hull",
        decomposition_workers=workers,
        decomposition_settings=part_settings_from_config(review.get("decomposition")),
    )
    if collision != "none":
        missing = [str(source) for source in visual if not collision_meshes.get(source)]
        if missing:
            raise ValueError(f"Retained parts have no collision geometry: {missing}")
    # These directories contain generated meshes. Remove older recipe/mode
    # outputs so inspection and camera fitting cannot pick up stale geometry.
    emitted = {Path(uri).name for uri in [*visual.values(), *stl.values()]}
    emitted.update(Path(uri).name for pieces in collision_meshes.values() for _, uri in pieces)
    for path in (output / "meshes").iterdir():
        if path.suffix in {".obj", ".stl"} and path.name not in emitted:
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
            },
            indent=2,
        )
        + "\n"
    )
    print(f"SDF: {sdf.relative_to(REPOSITORY_ROOT)}", flush=True)
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
    args = parser.parse_args()
    package = build(collision=args.collision, workers=args.workers, rebuild=args.rebuild)
    if args.view:
        if args.collision == "none":
            from view import view

            view(package)
        else:
            from collision_view import view

            view(package)


if __name__ == "__main__":
    main()
