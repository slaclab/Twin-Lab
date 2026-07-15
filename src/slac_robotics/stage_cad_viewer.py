"""Responsive viewer for reusable stage CAD occurrences."""

from __future__ import annotations

import json
import math
import os
import re
import socket
import time
from pathlib import Path
from typing import Any

import yaml
from OCP.Bnd import Bnd_Box
from OCP.BRep import BRep_Tool
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS

from .cad_motion import _leaf_occurrences, _placed_shape, _write_group_obj
from .constraints_wizard import _occurrence_shape_by_ref, _read_step_document


def prepare_stage_cad(
    inventory_path: str | Path,
    *,
    rebuild: bool = False,
    linear_deflection_mm: float = 2.0,
) -> Path:
    """Cache one real CAD mesh per reusable model plus occurrence transforms."""

    inventory_file = Path(inventory_path)
    inventory = yaml.safe_load(inventory_file.read_text(encoding="utf-8"))
    step_path = Path(inventory["source_step"])
    catalog_path = Path(inventory["stage_catalog"])
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))["stages"]
    manifest_path = Path(inventory["cad_manifest"])
    output_dir = inventory_file.with_name(
        inventory_file.name.removesuffix(".inventory.yaml") + ".stage-cad"
    )
    scene_path = output_dir / "scene.yaml"
    sources = [inventory_file, step_path, catalog_path, manifest_path]
    if not rebuild and scene_path.exists():
        cached_scene = yaml.safe_load(scene_path.read_text(encoding="utf-8"))
        cached_meshes = {Path(item["mesh"]) for item in cached_scene.get("instances", [])}
        if cached_scene.get("schema") == "slac-stage-cad-scene/v6" and cached_scene.get(
            "attachments"
        ):
            cached_meshes.update(Path(item["mesh"]) for item in cached_scene["attachments"])
            for stage_meshes in cached_scene.get("motion_stage_meshes", {}).values():
                cached_meshes.update(Path(path) for path in stage_meshes.values())
            if cached_meshes and _is_current([scene_path, *cached_meshes], sources):
                return scene_path

    output_dir.mkdir(exist_ok=True)
    document, _, roots = _read_step_document(step_path)
    assert document is not None
    geometries: dict[str, list[tuple[str, Any, Path]]] = {}
    instances = []
    for instance in inventory["stage_instances"]:
        model_id = str(instance["catalog"])
        shape, location = _occurrence_shape_by_ref(roots, str(instance["ref"]))
        model_geometries = geometries.setdefault(model_id, [])
        matched = next((item for item in model_geometries if shape.IsSame(item[1])), None)
        if matched is None:
            number = len(model_geometries) + 1
            geometry_id = model_id if number == 1 else f"{model_id}__definition_{number}"
            mesh_path = output_dir / f"{geometry_id}.obj"
            matched = (geometry_id, shape, mesh_path)
            model_geometries.append(matched)
        geometry_id, _, mesh_path = matched
        instances.append(
            {
                "ref": str(instance["ref"]),
                "library_id": str(instance["library_id"]),
                "catalog": model_id,
                "geometry_id": geometry_id,
                "model": str(catalog[model_id]["model"]),
                "joint_type": str(catalog[model_id]["joint_type"]),
                "mesh": mesh_path.as_posix(),
                **_transform_data(location.Transformation()),
            }
        )

    for model_geometries in geometries.values():
        for _, shape, mesh_path in model_geometries:
            _write_shape_obj(shape, mesh_path, linear_deflection_mm)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_items = manifest["occurrences"]
    by_ref = {item["ref"]: item for item in manifest_items}
    root_id = by_ref[inventory["subassembly"]["ref"]]["id"]
    stage_ids = [by_ref[str(item["ref"])]["id"] for item in inventory["stage_instances"]]
    hidden_refs = {str(ref) for ref in inventory.get("hidden_occurrences", [])}
    attached_refs = [
        item["ref"]
        for item in manifest_items
        if not item["is_assembly"]
        and item["id"].startswith(f"{root_id}/")
        and not any(item["id"].startswith(f"{stage_id}/") for stage_id in stage_ids)
        and not _is_fastener_name(str(item["name"]))
        and item["ref"] not in hidden_refs
    ]
    leaf_occurrences = _leaf_occurrences(roots)
    instance_by_ref = {item["ref"]: item for item in instances}
    motion_stage_meshes: dict[str, dict[str, str]] = {}
    motion_stage_roles: dict[str, set[str]] = {}
    for references in inventory.get("motion_chains", {}).values():
        for ref in references:
            motion_stage_roles.setdefault(str(ref), set()).update(("fixed", "moving"))
    for specs in inventory.get("compound_motion_chains", {}).values():
        for spec in specs:
            roles = motion_stage_roles.setdefault(str(spec["stage_ref"]), set())
            if spec.get("fixed_role"):
                roles.add(str(spec["fixed_role"]))
            roles.add(str(spec["moving_role"]))
    for stage_ref, requested_roles in motion_stage_roles.items():
        stage_item = instance_by_ref[stage_ref]
        roles = catalog[stage_item["catalog"]]["component_roles"]
        children = [item for item in manifest_items if item["parent_id"] == by_ref[stage_ref]["id"]]
        role_meshes = {}
        for role in sorted(requested_roles):
            references = [children[index - 1]["ref"] for index in roles[role]]
            mesh_path = output_dir / f"{stage_ref}_{role}.obj"
            _write_group_obj(
                [leaf_occurrences[ref] for ref in references],
                mesh_path,
                linear_deflection_mm=linear_deflection_mm,
            )
            role_meshes[role] = mesh_path.as_posix()
        motion_stage_meshes[stage_ref] = role_meshes

    attachment_groups: dict[str | None, list[str]] = {None: []}
    overrides = inventory.get("attachment_overrides", {})
    forced_fixed = {str(ref) for ref in overrides.get("fixed", [])}
    forced_parent = {
        str(ref): str(parent_ref)
        for parent_ref, references in overrides.get("moving", {}).items()
        for ref in references
    }
    chain_root_by_id = {
        os.path.commonpath([by_ref[str(ref)]["id"] for ref in refs]): refs
        for refs in inventory.get("motion_chains", {}).values()
    }
    for reference in attached_refs:
        if reference in forced_fixed:
            attachment_groups[None].append(reference)
            continue
        if reference in forced_parent:
            attachment_groups.setdefault(forced_parent[reference], []).append(reference)
            continue
        occurrence_id = by_ref[reference]["id"]
        chain_refs = next(
            (
                refs
                for branch_id, refs in chain_root_by_id.items()
                if occurrence_id.startswith(f"{branch_id}/")
            ),
            None,
        )
        if chain_refs is None:
            attachment_groups[None].append(reference)
            continue
        center_m = _shape_center_m(_placed_shape(leaf_occurrences[reference]))
        parent_ref = min(
            chain_refs,
            key=lambda ref: math.dist(center_m, instance_by_ref[ref]["translation_m"]),
        )
        attachment_groups.setdefault(parent_ref, []).append(reference)

    attachments = []
    for parent_ref, references in attachment_groups.items():
        if not references:
            continue
        name = "fixed" if parent_ref is None else parent_ref
        mesh_path = output_dir / f"attached_{name}.obj"
        _write_group_obj(
            [leaf_occurrences[ref] for ref in references],
            mesh_path,
            linear_deflection_mm=linear_deflection_mm,
        )
        attachments.append(
            {
                "parent_stage_ref": parent_ref,
                "mesh": mesh_path.as_posix(),
                "part_count": len(references),
            }
        )

    motion_chains = []
    for chain_name, references in inventory.get("motion_chains", {}).items():
        joints = []
        for reference in references:
            item = instance_by_ref[str(reference)]
            stage = catalog[item["catalog"]]
            axis_local = stage.get("axis_local")
            if axis_local is None or not isinstance(stage.get("limits"), list):
                continue
            axis_world = _rotate_vector(item["rotation"], axis_local)
            joints.append(
                {
                    "key": item["ref"],
                    "ref": item["ref"],
                    "stack": str(chain_name),
                    "name": "motion",
                    "model": item["model"],
                    "joint_type": item["joint_type"],
                    "fixed_role": "fixed",
                    "moving_role": "moving",
                    "axis_world": axis_world,
                    "origin_m": item["translation_m"],
                    "limits": _reviewed_limits(
                        inventory, item["ref"], item["ref"], stage["limits"]
                    ),
                    "home": _reviewed_home(inventory, item["ref"], item["ref"]),
                }
            )
        motion_chains.append({"name": str(chain_name), "joints": joints})

    for chain_name, specs in inventory.get("compound_motion_chains", {}).items():
        joints = []
        for spec in specs:
            item = instance_by_ref[str(spec["stage_ref"])]
            key = str(spec["key"])
            joints.append(
                {
                    "key": key,
                    "ref": item["ref"],
                    "stack": str(chain_name),
                    "name": str(spec["name"]),
                    "model": item["model"],
                    "joint_type": "prismatic",
                    "fixed_role": spec.get("fixed_role"),
                    "moving_role": str(spec["moving_role"]),
                    "axis_world": _rotate_vector(item["rotation"], spec["axis_local"]),
                    "origin_m": item["translation_m"],
                    "limits": _reviewed_limits(inventory, key, item["ref"], spec["limits"]),
                    "home": _reviewed_home(inventory, key, item["ref"]),
                }
            )
        motion_chains.append({"name": str(chain_name), "joints": joints})

    scene = {
        "schema": "slac-stage-cad-scene/v6",
        "source_inventory": inventory_file.as_posix(),
        "linear_deflection_mm": linear_deflection_mm,
        "instances": instances,
        "attached_part_count": len(attached_refs),
        "attachments": attachments,
        "motion_stage_meshes": motion_stage_meshes,
        "motion_chains": motion_chains,
    }
    scene_path.write_text(yaml.safe_dump(scene, sort_keys=False), encoding="utf-8")
    return scene_path


def view_stage_cad(scene_path: str | Path) -> None:
    """Show reusable real-CAD meshes with one transform per occurrence."""

    from pydrake.geometry import Mesh, Meshcat, MeshcatParams, Rgba
    from pydrake.math import RigidTransform, RotationMatrix

    scene = yaml.safe_load(Path(scene_path).read_text(encoding="utf-8"))
    instances = scene["instances"]
    params = MeshcatParams(host="*")
    wsl_address = _wsl_ipv4_address()
    if wsl_address is not None:
        params.web_url_pattern = f"http://{wsl_address}:{{port}}"
    meshcat = Meshcat(params)
    colors = {
        "prismatic": Rgba(0.52, 0.56, 0.62, 1.0),
        "revolute": Rgba(0.72, 0.55, 0.25, 1.0),
        "planar_xy": Rgba(0.35, 0.60, 0.42, 1.0),
    }
    role_paths: dict[tuple[str, str], str] = {}
    joint_paths: dict[str, str] = {}
    last_joint_path_by_stage: dict[str, str] = {}
    for chain in scene.get("motion_chains", []):
        parent_path = f"/chains/{chain['name']}"
        for joint in chain["joints"]:
            reference = joint["ref"]
            fixed_role = joint.get("fixed_role")
            if fixed_role:
                role_paths[(reference, fixed_role)] = (
                    f"{parent_path}/{reference} {fixed_role} geometry"
                )
            joint_path = f"{parent_path}/{joint['key']} motion"
            joint_paths[joint["key"]] = joint_path
            last_joint_path_by_stage[reference] = joint_path
            role_paths[(reference, joint["moving_role"])] = (
                f"{joint_path}/{reference} {joint['moving_role']} geometry"
            )
            parent_path = joint_path
    for item in instances:
        if item["ref"] in scene["motion_stage_meshes"]:
            meshes = scene["motion_stage_meshes"][item["ref"]]
            for role, mesh_path in meshes.items():
                meshcat.SetObject(
                    role_paths[(item["ref"], role)],
                    Mesh(Path(mesh_path), 1.0),
                    colors.get(item["joint_type"], Rgba(0.6, 0.6, 0.6, 1.0)),
                )
            continue
        path = f"/stages/{item['ref']} {item['model']}"
        meshcat.SetObject(
            path,
            Mesh(Path(item["mesh"]), 1.0),
            colors.get(item["joint_type"], Rgba(0.6, 0.6, 0.6, 1.0)),
        )
        meshcat.SetTransform(
            path,
            RigidTransform(RotationMatrix(item["rotation"]), item["translation_m"]),
        )

    for attachment in scene["attachments"]:
        parent_ref = attachment["parent_stage_ref"]
        if parent_ref in last_joint_path_by_stage:
            path = f"{last_joint_path_by_stage[parent_ref]}/attached geometry"
        elif parent_ref is not None:
            path = f"/pending motion/{parent_ref}/attached geometry"
        else:
            path = "/attached geometry/fixed"
        meshcat.SetObject(
            path,
            Mesh(Path(attachment["mesh"]), 1.0),
            Rgba(0.45, 0.68, 0.78, 1.0) if parent_ref is not None else Rgba(0.68, 0.68, 0.70, 1.0),
        )

    joints = [joint for chain in scene.get("motion_chains", []) for joint in chain["joints"]]
    for joint in joints:
        scale = 1000.0 if joint["joint_type"] == "prismatic" else 180.0 / math.pi
        unit = "mm" if joint["joint_type"] == "prismatic" else "deg"
        meshcat.AddSlider(
            _slider_label(joint, unit),
            joint["limits"][0] * scale,
            joint["limits"][1] * scale,
            0.1,
            joint["home"] * scale,
        )

    center = [
        sum(item["translation_m"][axis] for item in instances) / len(instances) for axis in range(3)
    ]
    meshcat.SetCameraPose(
        [center[0] + 0.8, center[1] + 0.8, center[2] + 0.8],
        center,
    )
    meshcat.AddButton("Reset to home")
    meshcat.AddButton("Stop viewer", "Escape")
    print(f"Reusable stage CAD: {meshcat.web_url()}")
    print(
        f"Showing {len(instances)} real stages and {scene['attached_part_count']} attached "
        "non-fastener parts."
    )
    print(f"Motion sliders: {len(joints)}")
    print("Press Escape in Meshcat or Ctrl-C here to stop.")
    reset_clicks = 0
    while meshcat.GetButtonClicks("Stop viewer") == 0:
        new_reset_clicks = meshcat.GetButtonClicks("Reset to home")
        if new_reset_clicks != reset_clicks:
            reset_clicks = new_reset_clicks
            for joint in joints:
                scale = 1000.0 if joint["joint_type"] == "prismatic" else 180.0 / math.pi
                unit = "mm" if joint["joint_type"] == "prismatic" else "deg"
                meshcat.SetSliderValue(_slider_label(joint, unit), joint["home"] * scale)
        for joint in joints:
            scale = 1000.0 if joint["joint_type"] == "prismatic" else 180.0 / math.pi
            unit = "mm" if joint["joint_type"] == "prismatic" else "deg"
            value = meshcat.GetSliderValue(_slider_label(joint, unit)) / scale - joint["home"]
            if joint["joint_type"] == "prismatic":
                transform = RigidTransform([component * value for component in joint["axis_world"]])
            else:
                transform = _rotation_about_axis(
                    joint["axis_world"], joint["origin_m"], value, RigidTransform, RotationMatrix
                )
            meshcat.SetTransform(joint_paths[joint["key"]], transform)
        time.sleep(0.1)


def _write_shape_obj(shape: Any, output: Path, linear_deflection_mm: float) -> None:
    vertices: list[tuple[float, float, float]] = []
    triangles: list[tuple[int, int, int]] = []
    BRepMesh_IncrementalMesh(shape, linear_deflection_mm, False, 0.5, True).Perform()
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        face = TopoDS.Face_s(explorer.Current())
        face_location = TopLoc_Location()
        triangulation = BRep_Tool.Triangulation_s(face, face_location)
        if triangulation is not None:
            offset = len(vertices)
            transform = face_location.Transformation()
            for index in range(1, triangulation.NbNodes() + 1):
                point = triangulation.Node(index).Transformed(transform)
                vertices.append((point.X() * 0.001, point.Y() * 0.001, point.Z() * 0.001))
            for index in range(1, triangulation.NbTriangles() + 1):
                triangle = triangulation.Triangle(index)
                n1, n2, n3 = (triangle.Value(i) for i in (1, 2, 3))
                if face.Orientation() == TopAbs_REVERSED:
                    n1, n2, n3 = n3, n2, n1
                triangles.append((offset + n1, offset + n2, offset + n3))
        explorer.Next()

    if not vertices or not triangles:
        raise ValueError(f"Stage produced no mesh triangles: {output.stem}")
    lines = [f"v {x:.9g} {y:.9g} {z:.9g}" for x, y, z in vertices]
    lines.extend(f"f {a} {b} {c}" for a, b, c in triangles)
    output.write_text("\n".join(lines) + "\n", encoding="ascii")


def _transform_data(transform: Any) -> dict[str, list[Any]]:
    rotation = [
        [float(transform.Value(row, column)) for column in range(1, 4)] for row in range(1, 4)
    ]
    for row in rotation:
        for index, value in enumerate(row):
            if math.isclose(value, 0.0, abs_tol=1e-14):
                row[index] = 0.0
    return {
        "rotation": rotation,
        "translation_m": [float(transform.Value(row, 4)) * 0.001 for row in range(1, 4)],
    }


def _is_fastener_name(name: str) -> bool:
    return re.search(r"screw|shcs|fhcs|setscr", name, re.IGNORECASE) is not None


def _rotate_vector(rotation: list[list[float]], vector: list[float]) -> list[float]:
    result = [
        sum(rotation[row][column] * vector[column] for column in range(3)) for row in range(3)
    ]
    norm = math.sqrt(sum(value * value for value in result))
    return [value / norm for value in result]


def _reviewed_limits(
    inventory: dict[str, Any], key: str, stage_ref: str, default: list[float]
) -> list[float]:
    overrides = inventory.get("joint_limit_overrides", {})
    override = overrides.get(key, overrides.get(stage_ref))
    if override is None:
        return [float(default[0]), float(default[1])]
    limits = [float(value) for value in override["limits"]]
    if override.get("unit") == "degree":
        return [math.radians(value) for value in limits]
    return limits


def _reviewed_home(inventory: dict[str, Any], key: str, stage_ref: str) -> float:
    overrides = inventory.get("joint_limit_overrides", {})
    override = overrides.get(key, overrides.get(stage_ref, {}))
    home = float(override.get("home", 0.0))
    return math.radians(home) if override.get("unit") == "degree" else home


def _slider_label(joint: dict[str, Any], unit: str) -> str:
    axis_name = "" if joint["name"] == "motion" else f" {joint['name']}"
    return f"{joint['stack']} / {joint['ref']}{axis_name} {joint['model']} ({unit})"


def _shape_center_m(shape: Any) -> list[float]:
    bounds = Bnd_Box()
    BRepBndLib.Add_s(shape, bounds, False)
    x_min, y_min, z_min, x_max, y_max, z_max = bounds.Get()
    return [(x_min + x_max) * 0.0005, (y_min + y_max) * 0.0005, (z_min + z_max) * 0.0005]


def _rotation_about_axis(axis, origin, angle, rigid_transform_type, rotation_matrix_type):
    x, y, z = axis
    c = math.cos(angle)
    s = math.sin(angle)
    t = 1.0 - c
    matrix = [
        [t * x * x + c, t * x * y - s * z, t * x * z + s * y],
        [t * x * y + s * z, t * y * y + c, t * y * z - s * x],
        [t * x * z - s * y, t * y * z + s * x, t * z * z + c],
    ]
    translation = [
        origin[row] - sum(matrix[row][column] * origin[column] for column in range(3))
        for row in range(3)
    ]
    return rigid_transform_type(rotation_matrix_type(matrix), translation)


def _is_current(outputs: list[Path], sources: list[Path]) -> bool:
    if not all(output.exists() for output in outputs):
        return False
    oldest_output = min(output.stat().st_mtime_ns for output in outputs)
    return all(source.exists() and source.stat().st_mtime_ns <= oldest_output for source in sources)


def _wsl_ipv4_address() -> str | None:
    if "WSL_DISTRO_NAME" not in os.environ:
        return None
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
            connection.connect(("1.1.1.1", 53))
            address = str(connection.getsockname()[0])
            return address if not address.startswith("127.") else None
    except OSError:
        return None


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="View reusable real stage CAD")
    parser.add_argument("stage_inventory")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--deflection-mm", type=float, default=2.0)
    args = parser.parse_args()

    scene = prepare_stage_cad(
        args.stage_inventory,
        rebuild=args.rebuild,
        linear_deflection_mm=args.deflection_mm,
    )
    print(f"Stage CAD cache: {scene.parent}")
    if not args.prepare_only:
        try:
            view_stage_cad(scene)
        except KeyboardInterrupt:
            print("\nStage CAD viewer stopped.")


if __name__ == "__main__":
    main()
