"""Extract a reviewable CAD manifest from a STEP assembly.

STEP provides geometry, occurrence hierarchy, and occurrence poses. It does not
provide a reliable robotics joint model. This tool therefore keeps generated CAD
facts separate from the small, human-reviewed kinematics overlay.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.Message import Message_ProgressRange
from OCP.RWGltf import RWGltf_CafWriter
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TCollection import TCollection_AsciiString, TCollection_ExtendedString
from OCP.TColStd import TColStd_IndexedDataMapOfStringString
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_Label, TDF_LabelSequence
from OCP.TDocStd import TDocStd_Document
from OCP.TopLoc import TopLoc_Location
from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool

from .paths import CACHE_ROOT, REPOSITORY_ROOT, resolve_repo_path

SUPPORTED_STEP_SUFFIXES = {".stp", ".step"}
REF_TOKEN = re.compile(r"\b[AP]\d{3}\b")


def extract_cad_manifest(step_path: str | Path) -> dict[str, Any]:
    """Return assembly occurrences, hierarchy, and local poses from STEP."""

    path = _validated_step_path(step_path)
    document, shape_tool, roots = _read_step_document(path)
    # Keep the XCAF document alive while its labels are traversed.
    assert document is not None
    occurrences: list[dict[str, Any]] = []

    for root_index in range(1, roots.Length() + 1):
        root = roots.Value(root_index)
        root_name = _label_name(root)
        root_id = f"root[{root_index}]/{root_name}"
        occurrences.append(
            {
                "id": root_id,
                "name": root_name,
                "parent_id": None,
                "depth": 0,
                "is_assembly": bool(XCAFDoc_ShapeTool.IsAssembly_s(root)),
                "transform_to_parent": _identity_transform(),
            }
        )
        _append_occurrences(
            shape_tool=shape_tool,
            parent=root,
            parent_id=root_id,
            depth=1,
            output=occurrences,
        )

    assembly_number = 0
    part_number = 0
    for occurrence in occurrences:
        if occurrence["is_assembly"]:
            assembly_number += 1
            occurrence["ref"] = f"A{assembly_number:03d}"
        else:
            part_number += 1
            occurrence["ref"] = f"P{part_number:03d}"

    return {
        "schema": "slac-cad-manifest/v1",
        "source_step": str(path),
        "transform_convention": "4x4 row-major transform from occurrence to parent",
        "length_unit": "millimeter",
        "occurrences": occurrences,
    }


def write_cad_manifest(
    step_path: str | Path,
    output_path: str | Path | None = None,
) -> Path:
    """Write the generated CAD facts beside the STEP assembly."""

    step = _validated_step_path(step_path)
    output = Path(output_path) if output_path else _default_manifest_path(step)
    manifest = extract_cad_manifest(step)
    output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return output


def write_kinematics_template(
    manifest_path: str | Path,
    output_path: str | Path | None = None,
    *,
    overwrite: bool = False,
) -> Path:
    """Write a compact review template that can later be compiled to SDF."""

    manifest = Path(manifest_path)
    output = Path(output_path) if output_path else _default_kinematics_path(manifest)
    if output.exists() and not overwrite:
        raise FileExistsError(
            f"Kinematics review already exists: {output}. "
            "Use --force-template only if you intend to replace your assignments."
        )
    manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    model_name = (
        manifest.parent.name
        if manifest.name == "manifest.json"
        else manifest.name.removesuffix(".cad.json")
    )
    catalog = "\n".join(
        f"#   {item['ref']}  {'  ' * int(item['depth'])}{item['name']}"
        for item in manifest_data["occurrences"]
    )
    text = f"""# STEP import succeeded. Use the short references below in rigid_groups.
# Assemblies start with A; assign leaf parts (P references) to rigid groups.
#
{catalog}

schema: slac-kinematics-review/v1
cad_manifest: {manifest.as_posix()}
model_name: {model_name}
notes:
  - This file contains human-reviewed intent; do not copy the full CAD tree here.
  - Occurrence IDs come from the generated CAD manifest.
  - All kinematic lengths are meters and angles are radians.

rigid_groups:
  base:
    occurrences: []
  x_carriage:
    occurrences: []
  y_carriage:
    occurrences: []
  z_carriage:
    occurrences: []

joints:
  - name: x
    type: prismatic
    parent_group: base
    child_group: x_carriage
    axis_xyz: [1.0, 0.0, 0.0]
    limits: [-0.05, 0.05]
    home: 0.0
    parent_to_joint:
      translation_m: [0.0, 0.0, 0.0]
      rotation_rpy_rad: [0.0, 0.0, 0.0]
  - name: y
    type: prismatic
    parent_group: x_carriage
    child_group: y_carriage
    axis_xyz: [0.0, 1.0, 0.0]
    limits: [-0.05, 0.05]
    home: 0.0
    parent_to_joint:
      translation_m: [0.0, 0.0, 0.0]
      rotation_rpy_rad: [0.0, 0.0, 0.0]
  - name: z
    type: prismatic
    parent_group: y_carriage
    child_group: z_carriage
    axis_xyz: [0.0, 0.0, 1.0]
    limits: [-0.05, 0.05]
    home: 0.0
    parent_to_joint:
      translation_m: [0.0, 0.0, 0.0]
      rotation_rpy_rad: [0.0, 0.0, 0.0]
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    return output


def remap_stage_inventory(
    inventory_path: str | Path,
    *,
    previous_manifest_path: str | Path,
    new_manifest_path: str | Path,
    output_path: str | Path | None = None,
    alias_map_path: str | Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Rewrite an inventory file against a new manifest, preserving comments and layout."""

    inventory_file = resolve_repo_path(inventory_path).resolve()
    previous_manifest_file = resolve_repo_path(previous_manifest_path).resolve()
    new_manifest_file = resolve_repo_path(new_manifest_path).resolve()
    output_file = Path(output_path).resolve() if output_path else inventory_file

    inventory_text = inventory_file.read_text(encoding="utf-8")
    inventory = yaml.safe_load(inventory_text)
    previous_manifest = json.loads(previous_manifest_file.read_text(encoding="utf-8"))
    new_manifest = json.loads(new_manifest_file.read_text(encoding="utf-8"))
    aliases = _load_aliases(alias_map_path)

    ref_map, unresolved = _build_manifest_ref_map(previous_manifest, new_manifest, aliases)
    remapped_text = _rewrite_inventory_text(
        inventory_text,
        ref_map,
        new_manifest_path=_portable_repo_path(new_manifest_file),
        subassembly_stats=_subassembly_stats(
            new_manifest, ref_map.get(str(inventory["subassembly"]["ref"]))
        ),
    )
    output_file.write_text(remapped_text, encoding="utf-8")

    return output_file, {
        "mapped_ref_count": len(ref_map),
        "unresolved_refs": sorted(unresolved),
        "alias_map": aliases,
    }


def _build_manifest_ref_map(
    previous_manifest: dict[str, Any],
    new_manifest: dict[str, Any],
    aliases: dict[str, dict[str, str]],
) -> tuple[dict[str, str], set[str]]:
    old_items = previous_manifest["occurrences"]
    new_items = new_manifest["occurrences"]
    new_by_id = {str(item["id"]): item for item in new_items}
    new_children: dict[str | None, list[dict[str, Any]]] = {}
    for item in new_items:
        new_children.setdefault(item["parent_id"], []).append(item)

    mapped_ids: dict[str, str] = {}
    ref_map: dict[str, str] = {}
    unresolved: set[str] = set()

    for item in sorted(old_items, key=lambda occurrence: int(occurrence["depth"])):
        old_id = str(item["id"])
        new_item = _resolve_occurrence_match(item, mapped_ids, new_by_id, new_children, aliases)
        if new_item is None:
            unresolved.add(str(item["ref"]))
            continue
        mapped_ids[old_id] = str(new_item["id"])
        ref_map[str(item["ref"])] = str(new_item["ref"])

    return ref_map, unresolved


def _resolve_occurrence_match(
    item: dict[str, Any],
    mapped_ids: dict[str, str],
    new_by_id: dict[str, dict[str, Any]],
    new_children: dict[str | None, list[dict[str, Any]]],
    aliases: dict[str, dict[str, str]],
) -> dict[str, Any] | None:
    old_id = str(item["id"])
    if old_id in new_by_id:
        return new_by_id[old_id]

    occurrence_aliases = aliases["occurrence_id_aliases"]
    if old_id in occurrence_aliases and occurrence_aliases[old_id] in new_by_id:
        return new_by_id[occurrence_aliases[old_id]]

    parent_id = item["parent_id"]
    mapped_parent_id = mapped_ids.get(str(parent_id)) if parent_id is not None else None
    candidates = [
        candidate
        for candidate in new_children.get(mapped_parent_id, [])
        if bool(candidate["is_assembly"]) == bool(item["is_assembly"])
    ]
    if not candidates:
        return None

    expected_names = {
        str(item["name"]),
        aliases["name_aliases"].get(str(item["name"]), str(item["name"])),
        _transform_occurrence_name(str(item["name"]), aliases["name_aliases"]),
    }
    expected_names.discard("")
    named = [candidate for candidate in candidates if str(candidate["name"]) in expected_names]
    if len(named) == 1:
        return named[0]

    transformed_id = _transform_occurrence_id(old_id, aliases["name_aliases"])
    terminal = transformed_id.rsplit("/", 1)[-1]
    id_like = [
        candidate for candidate in candidates if str(candidate["id"]).rsplit("/", 1)[-1] == terminal
    ]
    if len(id_like) == 1:
        return id_like[0]

    return None


def _load_aliases(alias_map_path: str | Path | None) -> dict[str, dict[str, str]]:
    if alias_map_path is None:
        return {"occurrence_id_aliases": {}, "name_aliases": {}}
    alias_file = resolve_repo_path(alias_map_path).resolve()
    loaded = yaml.safe_load(alias_file.read_text(encoding="utf-8"))
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        raise ValueError("Alias map must contain a YAML object")
    return {
        "occurrence_id_aliases": {
            str(key): str(value) for key, value in loaded.get("occurrence_id_aliases", {}).items()
        },
        "name_aliases": {
            str(key): str(value) for key, value in loaded.get("name_aliases", {}).items()
        },
    }


def _transform_occurrence_id(occurrence_id: str, name_aliases: dict[str, str]) -> str:
    parts = occurrence_id.split("/")
    return "/".join(_transform_occurrence_name(part, name_aliases) for part in parts)


def _transform_occurrence_name(name: str, name_aliases: dict[str, str]) -> str:
    prefix, separator, suffix = name.partition(":")
    if not separator:
        return name_aliases.get(name, name)
    return f"{prefix}:{name_aliases.get(suffix, suffix)}"


def _rewrite_inventory_text(
    text: str,
    ref_map: dict[str, str],
    *,
    new_manifest_path: str,
    subassembly_stats: dict[str, int] | None,
) -> str:
    remapped = REF_TOKEN.sub(lambda match: ref_map.get(match.group(0), match.group(0)), text)
    remapped = re.sub(r"(?m)^cad_manifest:\s+.+$", f"cad_manifest: {new_manifest_path}", remapped)
    if subassembly_stats is not None:
        remapped = re.sub(
            r"(?m)^(\s*occurrence_count:)\s+\d+$",
            rf"\1 {subassembly_stats['occurrence_count']}",
            remapped,
        )
        remapped = re.sub(
            r"(?m)^(\s*assembly_count:)\s+\d+$",
            rf"\1 {subassembly_stats['assembly_count']}",
            remapped,
        )
        remapped = re.sub(
            r"(?m)^(\s*leaf_part_count:)\s+\d+$",
            rf"\1 {subassembly_stats['leaf_part_count']}",
            remapped,
        )
    return remapped


def _portable_repo_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPOSITORY_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _subassembly_stats(
    manifest: dict[str, Any], subassembly_ref: str | None
) -> dict[str, int] | None:
    if subassembly_ref is None:
        return None
    by_ref = {str(item["ref"]): item for item in manifest["occurrences"]}
    item = by_ref.get(subassembly_ref)
    if item is None:
        return None
    root_id = str(item["id"])
    members = [
        occurrence
        for occurrence in manifest["occurrences"]
        if str(occurrence["id"]) == root_id or str(occurrence["id"]).startswith(f"{root_id}/")
    ]
    assembly_count = sum(bool(occurrence["is_assembly"]) for occurrence in members)
    return {
        "occurrence_count": len(members),
        "assembly_count": assembly_count,
        "leaf_part_count": len(members) - assembly_count,
    }


def manifest_tree_lines(manifest: dict[str, Any]) -> list[str]:
    """Render occurrence IDs as an indented review tree."""

    return [
        f"{'  ' * int(item['depth'])}- [{item['ref']}] {item['name']}"
        for item in manifest["occurrences"]
    ]


def write_step_preview(
    step_path: str | Path,
    output_path: str | Path | None = None,
    *,
    linear_deflection_mm: float = 0.5,
    focus_ref: str | None = None,
    focus_refs: list[str] | None = None,
) -> Path:
    """Tessellate a STEP assembly to glTF for lightweight visual inspection."""

    step = _validated_step_path(step_path)
    document, _, roots = _read_step_document(step)
    if focus_ref is not None and focus_refs is not None:
        raise ValueError("Use either focus_ref or focus_refs, not both")
    selected_refs = focus_refs if focus_refs is not None else ([focus_ref] if focus_ref else [])
    if selected_refs:
        focused_document = TDocStd_Document(TCollection_ExtendedString("slac-focused-preview"))
        focused_shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(focused_document.Main())
        for selected_ref in selected_refs:
            shape, location = _occurrence_shape_by_ref(roots, selected_ref)
            placed = BRepBuilderAPI_Transform(shape, location.Transformation(), True).Shape()
            focused_shape_tool.AddShape(placed, True, True)
        document = focused_document
        roots = TDF_LabelSequence()
        focused_shape_tool.GetFreeShapes(roots)

    for index in range(1, roots.Length() + 1):
        shape = XCAFDoc_ShapeTool.GetShape_s(roots.Value(index))
        BRepMesh_IncrementalMesh(
            shape,
            linear_deflection_mm,
            False,
            0.5,
            True,
        ).Perform()

    output = (
        Path(output_path)
        if output_path
        else step.with_name(
            f"{step.stem}.{focus_ref}.preview.gltf" if focus_ref else f"{step.stem}.preview.gltf"
        )
    )
    writer = RWGltf_CafWriter(TCollection_AsciiString(str(output)), False)
    writer.SetParallel(True)
    succeeded = writer.Perform(
        document,
        TColStd_IndexedDataMapOfStringString(),
        Message_ProgressRange(),
    )
    if not succeeded:
        raise RuntimeError(f"Failed to write STEP preview: {output}")
    return output


def check_kinematics_review(review_path: str | Path) -> dict[str, Any]:
    """Check group assignments and joint references without building a model."""

    review_file = Path(review_path)
    review = yaml.safe_load(review_file.read_text(encoding="utf-8"))
    if not isinstance(review, dict):
        raise ValueError("Kinematics review must contain a YAML object")

    manifest_path = resolve_repo_path(
        str(review.get("cad_manifest", "")), relative_to=review_file.parent
    )
    if not manifest_path.exists():
        raise FileNotFoundError(f"CAD manifest referenced by review was not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    known_parts = {item["ref"]: item for item in manifest["occurrences"] if not item["is_assembly"]}

    groups = review.get("rigid_groups", {})
    if not isinstance(groups, dict) or not groups:
        raise ValueError("rigid_groups must contain at least one group")
    assigned_to: dict[str, list[str]] = {}
    for group_name, group in groups.items():
        if not isinstance(group, dict):
            raise ValueError(f"Rigid group '{group_name}' must be an object")
        references = group.get("occurrences", [])
        if not isinstance(references, list):
            raise ValueError(f"Rigid group '{group_name}' occurrences must be a list")
        for reference in references:
            assigned_to.setdefault(str(reference), []).append(str(group_name))

    unknown = sorted(set(assigned_to) - set(known_parts))
    duplicate = sorted(ref for ref, owners in assigned_to.items() if len(owners) > 1)
    assigned = sorted(set(assigned_to) & set(known_parts))
    unassigned = sorted(set(known_parts) - set(assigned_to))

    group_names = set(groups)
    joint_errors: list[str] = []
    joints = review.get("joints", [])
    if not isinstance(joints, list):
        raise ValueError("joints must be a list")
    for index, joint in enumerate(joints, start=1):
        if not isinstance(joint, dict):
            joint_errors.append(f"joint {index} is not an object")
            continue
        for field in ("parent_group", "child_group"):
            group_name = joint.get(field)
            if group_name not in group_names:
                joint_errors.append(
                    f"joint '{joint.get('name', index)}' references unknown {field} '{group_name}'"
                )

    return {
        "manifest": manifest_path,
        "part_count": len(known_parts),
        "group_count": len(groups),
        "joint_count": len(joints),
        "assigned": assigned,
        "unassigned": unassigned,
        "unknown": unknown,
        "duplicate": duplicate,
        "joint_errors": joint_errors,
        "part_names": {ref: item["name"] for ref, item in known_parts.items()},
    }


def status_lines(status: dict[str, Any]) -> list[str]:
    """Render an actionable, user-facing review status."""

    names = status["part_names"]
    lines = [
        "Kinematics review status",
        f"  Parts assigned:   {len(status['assigned'])}/{status['part_count']}",
        f"  Rigid groups:     {status['group_count']}",
        f"  Joints described: {status['joint_count']}",
    ]
    for heading, key in (
        ("Unassigned parts", "unassigned"),
        ("Unknown references", "unknown"),
        ("Assigned more than once", "duplicate"),
    ):
        references = status[key]
        if references:
            lines.append(f"{heading}:")
            lines.extend(f"  - {ref}: {names.get(ref, '<not in manifest>')}" for ref in references)
    if status["joint_errors"]:
        lines.append("Joint errors:")
        lines.extend(f"  - {error}" for error in status["joint_errors"])
    if not status["unassigned"] and not any(
        status[key] for key in ("unknown", "duplicate", "joint_errors")
    ):
        lines.append("Ready for SDF compilation.")
    else:
        lines.append("Next: assign each interference-significant P reference to one rigid group.")
    return lines


def view_step_preview(preview_path: str | Path) -> None:
    """Display the STEP-derived glTF in Meshcat until Enter is pressed."""

    from pydrake.geometry import Mesh, Meshcat

    preview = Path(preview_path).resolve()
    meshcat = Meshcat()
    # OCCT's glTF writer converts its millimetre working units to glTF metres.
    meshcat.SetObject("/STEP assembly", Mesh(preview, 1.0))
    # Start close enough for compact positioning hardware to be unmistakable.
    meshcat.SetCameraPose([0.4, 0.4, 0.4], [0.0, 0.0, 0.0])
    print(f"STEP preview: {meshcat.web_url()}")
    input("Press Enter to close the preview... ")


def _append_occurrences(
    *,
    shape_tool: Any,
    parent: Any,
    parent_id: str,
    depth: int,
    output: list[dict[str, Any]],
) -> None:
    children = TDF_LabelSequence()
    XCAFDoc_ShapeTool.GetComponents_s(parent, children)

    for child_index in range(1, children.Length() + 1):
        child = children.Value(child_index)
        name = _component_name(child)
        occurrence_id = f"{parent_id}/{child_index}:{name}"
        referred = _referred_label(child)
        recurse_target = referred if referred is not None else child
        location = XCAFDoc_ShapeTool.GetLocation_s(child)
        output.append(
            {
                "id": occurrence_id,
                "name": name,
                "parent_id": parent_id,
                "depth": depth,
                "is_assembly": bool(XCAFDoc_ShapeTool.IsAssembly_s(recurse_target)),
                "transform_to_parent": _transform_matrix(location.Transformation()),
            }
        )
        if XCAFDoc_ShapeTool.IsAssembly_s(recurse_target):
            _append_occurrences(
                shape_tool=shape_tool,
                parent=recurse_target,
                parent_id=occurrence_id,
                depth=depth + 1,
                output=output,
            )


def _read_step_document(path: Path) -> tuple[Any, Any, Any]:
    document = TDocStd_Document(TCollection_ExtendedString("slac-cad-manifest"))
    reader = STEPCAFControl_Reader()
    status = reader.ReadFile(str(path))
    if not str(status).endswith("RetDone"):
        raise ValueError(f"Failed to read STEP file: {path} (status={status})")
    if not reader.Transfer(document):
        raise ValueError(f"Failed to transfer STEP assembly: {path}")

    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    roots = TDF_LabelSequence()
    shape_tool.GetFreeShapes(roots)
    if roots.Length() == 0:
        raise ValueError(f"STEP assembly contains no free shapes: {path}")
    return document, shape_tool, roots


def _occurrence_shape_by_ref(roots: Any, wanted_ref: str) -> tuple[Any, Any]:
    """Find an assembled occurrence using the same refs as the CAD manifest."""

    counters = {"assembly": 0, "part": 0}

    def walk(label: Any, parent_location: Any, *, is_root: bool = False) -> tuple[Any, Any] | None:
        referred = None if is_root else _referred_label(label)
        target = label if referred is None else referred
        is_assembly = bool(XCAFDoc_ShapeTool.IsAssembly_s(target))
        key = "assembly" if is_assembly else "part"
        counters[key] += 1
        current_ref = f"{'A' if is_assembly else 'P'}{counters[key]:03d}"
        local = TopLoc_Location() if is_root else XCAFDoc_ShapeTool.GetLocation_s(label)
        global_location = parent_location.Multiplied(local)

        if current_ref == wanted_ref:
            return XCAFDoc_ShapeTool.GetShape_s(target), global_location
        if is_assembly:
            children = TDF_LabelSequence()
            XCAFDoc_ShapeTool.GetComponents_s(target, children)
            for index in range(1, children.Length() + 1):
                found = walk(children.Value(index), global_location)
                if found is not None:
                    return found
        return None

    identity = TopLoc_Location()
    for index in range(1, roots.Length() + 1):
        found = walk(roots.Value(index), identity, is_root=True)
        if found is not None:
            return found
    raise ValueError(f"Occurrence ref not found in STEP assembly: {wanted_ref}")


def _component_name(label: Any) -> str:
    name = _label_name(label)
    if name != "<unnamed>":
        return name
    referred = _referred_label(label)
    return _label_name(referred) if referred is not None else name


def _label_name(label: Any) -> str:
    attribute = TDataStd_Name()
    if label.FindAttribute(TDataStd_Name.GetID_s(), attribute):
        return attribute.Get().ToExtString()
    return "<unnamed>"


def _referred_label(label: Any) -> Any | None:
    referred = TDF_Label()
    if XCAFDoc_ShapeTool.GetReferredShape_s(label, referred):
        return referred
    return None


def _transform_matrix(transform: Any) -> list[list[float]]:
    return [
        [float(transform.Value(row, column)) for column in range(1, 5)] for row in range(1, 4)
    ] + [[0.0, 0.0, 0.0, 1.0]]


def _identity_transform() -> list[list[float]]:
    return [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def _validated_step_path(step_path: str | Path) -> Path:
    path = Path(step_path)
    if not path.exists():
        raise FileNotFoundError(f"STEP file not found: {path}")
    if path.suffix.lower() not in SUPPORTED_STEP_SUFFIXES:
        raise ValueError(f"Expected a STEP file ({sorted(SUPPORTED_STEP_SUFFIXES)}): {path}")
    return path


def _default_manifest_path(step_path: Path) -> Path:
    if step_path.name == "source.stp" and step_path.parent.parent.name == "cad":
        return step_path.parent / "manifest.json"
    return step_path.with_suffix(".cad.json")


def _default_kinematics_path(manifest_path: Path) -> Path:
    if manifest_path.name == "manifest.json" and manifest_path.parent.parent.name == "cad":
        return manifest_path.parent / "reviews" / "kinematics.yaml"
    return manifest_path.with_name(
        manifest_path.name.removesuffix(".cad.json") + ".kinematics.yaml"
    )


def _default_preview_path(step_path: Path, preview_tag: str | None) -> Path:
    project = step_path.parent.name if step_path.name == "source.stp" else step_path.stem
    suffix = f".{preview_tag}" if preview_tag else ""
    return CACHE_ROOT / "previews" / project / f"preview{suffix}.gltf"


def _outputs_are_fresh(source: Path, outputs: list[Path]) -> bool:
    """Return whether every generated output is at least as new as its source."""

    return all(
        output.exists() and output.stat().st_mtime_ns >= source.stat().st_mtime_ns
        for output in outputs
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Generate a CAD manifest from STEP")
    parser.add_argument("step_file")
    parser.add_argument("--manifest-output")
    parser.add_argument("--kinematics-output")
    parser.add_argument("--manifest-only", action="store_true")
    parser.add_argument("--show-tree", action="store_true")
    preview_selection = parser.add_mutually_exclusive_group()
    preview_selection.add_argument(
        "--focus",
        metavar="A_REF",
        help="Preview only one assembly occurrence, for example A035",
    )
    preview_selection.add_argument(
        "--stage-inventory",
        help="Preview only stage occurrences listed in a stage inventory YAML",
    )
    parser.add_argument(
        "--refresh-manifest",
        action="store_true",
        help="Re-read STEP hierarchy even when the generated manifest is current",
    )
    parser.add_argument(
        "--refresh-preview",
        action="store_true",
        help="Retessellate the STEP even when the generated preview is current",
    )
    parser.add_argument(
        "--preview-deflection-mm",
        type=float,
        help="Preview tessellation tolerance; defaults to 2 mm for STEP files over 50 MB",
    )
    parser.add_argument(
        "--no-preview",
        action="store_true",
        help="Skip creation of the browser-viewable glTF preview",
    )
    parser.add_argument(
        "--view",
        action="store_true",
        help="Open the generated STEP preview in Meshcat",
    )
    parser.add_argument(
        "--force-template",
        action="store_true",
        help="Replace an existing kinematics review template",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check assignments in the kinematics review after generation",
    )
    parser.add_argument(
        "--remap-stage-inventory",
        help="Rewrite a reviewed stage inventory against the newly generated manifest",
    )
    parser.add_argument(
        "--previous-manifest",
        help="Manifest for the previous STEP revision; required for inventory remapping",
    )
    parser.add_argument(
        "--alias-map",
        help="YAML file mapping copied Teamcenter names or occurrence IDs to new ones",
    )
    parser.add_argument(
        "--remapped-inventory-output",
        help="Write the remapped inventory to a different path instead of replacing it in place",
    )
    args = parser.parse_args()

    step_path = _validated_step_path(args.step_file)
    manifest_path = (
        Path(args.manifest_output) if args.manifest_output else _default_manifest_path(step_path)
    )
    manifest_cached = not args.refresh_manifest and _outputs_are_fresh(step_path, [manifest_path])
    if not manifest_cached:
        manifest_path = write_cad_manifest(step_path, manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assembly_count = sum(item["is_assembly"] for item in manifest["occurrences"])
    part_count = len(manifest["occurrences"]) - assembly_count
    print("STEP READ OK")
    print(f"  Assemblies: {assembly_count}")
    print(f"  Leaf parts: {part_count}")
    print(f"  CAD manifest: {manifest_path}{' (cached)' if manifest_cached else ''}")

    if args.remap_stage_inventory:
        if not args.previous_manifest:
            parser.error("--remap-stage-inventory requires --previous-manifest")
        remapped_inventory, report = remap_stage_inventory(
            args.remap_stage_inventory,
            previous_manifest_path=args.previous_manifest,
            new_manifest_path=manifest_path,
            output_path=args.remapped_inventory_output,
            alias_map_path=args.alias_map,
        )
        print(f"  Remapped inventory: {remapped_inventory}")
        print(f"  Remapped refs: {report['mapped_ref_count']}")
        if report["unresolved_refs"]:
            print("  Unresolved refs:")
            for reference in report["unresolved_refs"]:
                print(f"    - {reference}")
        else:
            print("  Unresolved refs: none")

    if args.show_tree:
        print("\nAssembly tree")
        print("\n".join(manifest_tree_lines(manifest)))

    preview_path = None
    if not args.no_preview:
        inventory_refs: list[str] | None = None
        preview_tag = args.focus
        if args.stage_inventory:
            inventory_path = resolve_repo_path(args.stage_inventory)
            inventory = yaml.safe_load(inventory_path.read_text(encoding="utf-8"))
            inventory_refs = [str(item["ref"]) for item in inventory["stage_instances"]]
            preview_tag = f"{inventory['subassembly']['ref']}.stages"
        preview_path = _default_preview_path(step_path, preview_tag)
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        preview_outputs = [preview_path, preview_path.with_suffix(".bin")]
        preview_cached = not args.refresh_preview and _outputs_are_fresh(step_path, preview_outputs)
        if not preview_cached:
            deflection_mm = args.preview_deflection_mm
            if deflection_mm is None:
                deflection_mm = 2.0 if step_path.stat().st_size > 50_000_000 else 0.5
            preview_path = write_step_preview(
                step_path,
                preview_path,
                linear_deflection_mm=deflection_mm,
                focus_ref=args.focus,
                focus_refs=inventory_refs,
            )
            if inventory_refs is not None:
                print(f"  Stage occurrences: {len(inventory_refs)}")
            print(f"  Preview tolerance: {deflection_mm:g} mm")
        print(f"  STEP preview: {preview_path}{' (cached)' if preview_cached else ''}")

    template_path = (
        Path(args.kinematics_output)
        if args.kinematics_output
        else _default_kinematics_path(manifest_path)
    )
    if not args.manifest_only:
        try:
            template_path = write_kinematics_template(
                manifest_path,
                args.kinematics_output,
                overwrite=args.force_template,
            )
            print(f"  Kinematics review: {template_path}")
        except FileExistsError:
            print(f"  Kinematics review: {template_path} (kept existing assignments)")

    if args.check:
        if not template_path.exists():
            parser.error(f"Cannot check missing kinematics review: {template_path}")
        print()
        print("\n".join(status_lines(check_kinematics_review(template_path))))

    if args.view:
        if preview_path is None:
            parser.error("--view cannot be combined with --no-preview")
        view_step_preview(preview_path)
    else:
        print("\nNext steps")
        print(f"  1. View the STEP: slac-cad-manifest {args.step_file} --view")
        if not args.manifest_only:
            print(f"  2. Edit rigid_groups in: {template_path}")
            print(f"  3. Check progress: slac-cad-manifest {args.step_file} --check --no-preview")


if __name__ == "__main__":
    main()
