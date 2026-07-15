"""Utilities to bootstrap joint-constraint configs from assembly STEP files.

Run:
    python -m slac_robotics.constraints_wizard step_files/your_assembly.stp
"""

from __future__ import annotations

import importlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


def _ocp_symbol(module_name: str, symbol_name: str) -> Any:
    module = importlib.import_module(module_name)
    return getattr(module, symbol_name)


STEPCAFControl_Reader = _ocp_symbol("OCP.STEPCAFControl", "STEPCAFControl_Reader")
TCollection_ExtendedString = _ocp_symbol("OCP.TCollection", "TCollection_ExtendedString")
TDF_Label = _ocp_symbol("OCP.TDF", "TDF_Label")
TDF_LabelSequence = _ocp_symbol("OCP.TDF", "TDF_LabelSequence")
TDataStd_Name = _ocp_symbol("OCP.TDataStd", "TDataStd_Name")
TDocStd_Document = _ocp_symbol("OCP.TDocStd", "TDocStd_Document")
XCAFDoc_DocumentTool = _ocp_symbol("OCP.XCAFDoc", "XCAFDoc_DocumentTool")
XCAFDoc_ShapeTool = _ocp_symbol("OCP.XCAFDoc", "XCAFDoc_ShapeTool")


_SUPPORTED_STEP_SUFFIXES = {".stp", ".step"}


def _ensure_supported_step_path(path: Path) -> None:
    suffix = path.suffix.lower()
    if suffix in _SUPPORTED_STEP_SUFFIXES:
        return

    raise ValueError(
        "Unsupported CAD format for constraints wizard. STEP is required "
        f"({sorted(_SUPPORTED_STEP_SUFFIXES)}), got: {path.suffix or '<none>'}. "
        "For Solid Edge Parasolid (.x_t/.x_b), export assembly as STEP AP242/AP214."
    )


def list_step_components(step_path: str | Path, recursive: bool = False) -> list[str]:
    """Return component names from an assembly STEP file.

    When recursive is False, only first-level children under each free-shape root
    are returned. When recursive is True, nested subcomponents are included.
    """
    path = Path(step_path)
    if not path.exists():
        raise FileNotFoundError(f"STEP file not found: {path}")
    _ensure_supported_step_path(path)

    doc = TDocStd_Document(TCollection_ExtendedString("slac-step-doc"))
    reader = STEPCAFControl_Reader()
    status = reader.ReadFile(str(path))
    if str(status).endswith("RetDone") is False:
        raise ValueError(f"Failed to read STEP file: {path} (status={status})")

    transferred = reader.Transfer(doc)
    if not transferred:
        raise ValueError(f"Failed to transfer STEP data into document: {path}")

    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    roots = TDF_LabelSequence()
    shape_tool.GetFreeShapes(roots)
    if roots.Length() == 0:
        return []

    components: list[str] = []
    for i in range(1, roots.Length() + 1):
        root = roots.Value(i)
        components.extend(_collect_components(root, recursive=recursive))

    return components


def list_step_tree(step_path: str | Path) -> list[str]:
    """Return a textual tree of assembly components."""
    hierarchy = list_step_hierarchy(step_path)
    lines: list[str] = []
    for node in hierarchy:
        lines.append(node["name"])
        lines.extend(_hierarchy_to_lines(node["children"], depth=1))
    return lines


def list_step_hierarchy(step_path: str | Path, recursive: bool = True) -> list[dict[str, Any]]:
    """Return nested assembly hierarchy as JSON-serializable dicts."""
    path = Path(step_path)
    if not path.exists():
        raise FileNotFoundError(f"STEP file not found: {path}")
    _ensure_supported_step_path(path)

    doc = TDocStd_Document(TCollection_ExtendedString("slac-step-doc"))
    reader = STEPCAFControl_Reader()
    status = reader.ReadFile(str(path))
    if str(status).endswith("RetDone") is False:
        raise ValueError(f"Failed to read STEP file: {path} (status={status})")

    transferred = reader.Transfer(doc)
    if not transferred:
        raise ValueError(f"Failed to transfer STEP data into document: {path}")

    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    roots = TDF_LabelSequence()
    shape_tool.GetFreeShapes(roots)
    if roots.Length() == 0:
        return []

    nodes: list[dict[str, Any]] = []
    for i in range(1, roots.Length() + 1):
        root = roots.Value(i)
        nodes.append(
            {
                "name": _label_name(root),
                "children": _collect_hierarchy_nodes(root, recursive=recursive),
            }
        )
    return nodes


def write_constraints_template(
    step_path: str | Path,
    output_path: str | Path | None = None,
    recursive: bool = False,
) -> Path:
    """Write a JSON constraints template beside the STEP file."""
    step = Path(step_path)
    component_names = list_step_components(step, recursive=recursive)
    hierarchy_rows = list_step_hierarchy_rows(step, recursive=recursive)
    if not component_names:
        raise ValueError("No assembly components were discovered in the STEP file")

    template = {
        "assembly_step": str(step),
        "notes": [
            "Set base_components to fixed structure that does not move.",
            "Create one entry per motorized axis in joints.",
            "Each joint components list should include all parts that move together on that axis.",
            "Units: meters for limits_m and home_m.",
        ],
        "base_components": [],
        "assembly_hierarchy": [row["name"] for row in hierarchy_rows],
        "joints": [
            {
                "name": "linear_motor_1",
                "type": "linear",
                "axis_xyz": [1.0, 0.0, 0.0],
                "limits_m": [0.0, 0.05],
                "home_m": 0.0,
                "components": [],
            },
            {
                "name": "linear_motor_2",
                "type": "linear",
                "axis_xyz": [0.0, 1.0, 0.0],
                "limits_m": [0.0, 0.05],
                "home_m": 0.0,
                "components": [],
            },
            {
                "name": "linear_motor_3",
                "type": "linear",
                "axis_xyz": [0.0, 0.0, 1.0],
                "limits_m": [0.0, 0.05],
                "home_m": 0.0,
                "components": [],
            },
        ],
    }

    out = Path(output_path) if output_path else step.with_suffix(".constraints.json")
    out.write_text(_render_constraints_json(template, hierarchy_rows), encoding="utf-8")
    return out


def _render_constraints_json(template: dict[str, Any], hierarchy_rows: list[dict[str, Any]]) -> str:
    """Render JSON with tab indentation and visually nested hierarchy lines."""
    dumped = json.dumps(template, indent="\t", ensure_ascii=False)
    return _replace_hierarchy_block(dumped, hierarchy_rows)


def _replace_hierarchy_block(text: str, hierarchy_rows: list[dict[str, Any]]) -> str:
    marker = '"assembly_hierarchy": ['
    key_start = text.find(marker)
    if key_start < 0:
        return text

    open_bracket = text.find("[", key_start)
    if open_bracket < 0:
        return text

    close_bracket = _find_matching_bracket(text, open_bracket)
    if close_bracket < 0:
        return text

    custom_lines = ["\t\"assembly_hierarchy\": ["]
    for idx, row in enumerate(hierarchy_rows):
        suffix = "," if idx < len(hierarchy_rows) - 1 else ""
        depth = int(row.get("depth", 0))
        name = str(row.get("name", ""))
        custom_lines.append(f"\t\t{'\t' * depth}{json.dumps(name, ensure_ascii=False)}{suffix}")
    custom_lines.append("\t]")
    custom_block = "\n".join(custom_lines)

    return text[:key_start] + custom_block + text[close_bracket + 1 :]


def _find_matching_bracket(text: str, open_index: int) -> int:
    depth = 0
    in_string = False
    escaped = False

    for i in range(open_index, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue

        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return i

    return -1


def _label_name(label: Any) -> str:
    name = TDataStd_Name()
    if label.FindAttribute(TDataStd_Name.GetID_s(), name):
        return name.Get().ToExtString()
    return "<unnamed>"


def _dedupe_names(names: list[str]) -> list[str]:
    counter = Counter(names)
    used: dict[str, int] = {}
    out: list[str] = []
    for item in names:
        if counter[item] == 1:
            out.append(item)
            continue

        used[item] = used.get(item, 0) + 1
        out.append(f"{item}#{used[item]}")
    return out


def _print_parts(step_file: str, unique: bool, output: str | None, recursive: bool) -> None:
    parts = list_step_components(step_file, recursive=recursive)
    if unique:
        parts = sorted(set(parts))

    if output:
        out = Path(output)
        out.write_text("\n".join(parts) + "\n", encoding="utf-8")
        print(f"Wrote {len(parts)} part names to: {out}")
        return

    for part in parts:
        print(part)
    print(f"Total parts: {len(parts)}")


def _print_tree(step_file: str, output: str | None) -> None:
    lines = list_step_tree(step_file)
    text = "\n".join(lines) + "\n"

    if output:
        out = Path(output)
        out.write_text(text, encoding="utf-8")
        print(f"Wrote assembly tree ({len(lines)} lines) to: {out}")
        return

    print(text, end="")
    print(f"Total tree lines: {len(lines)}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate constraints template or print STEP assembly part names"
    )
    parser.add_argument("step_file", nargs="?", help="Path to STEP assembly file")
    parser.add_argument(
        "--output",
        default=None,
        help=(
            "Output JSON path for template mode, or text file path for --list-parts mode "
            "(default template output: <step_file>.constraints.json)"
        ),
    )
    parser.add_argument(
        "--list-parts",
        action="store_true",
        help=(
            "Print part names from assembly components (recursive by default) "
            "instead of writing template"
        ),
    )
    parser.add_argument(
        "--unique",
        action="store_true",
        help="With --list-parts, print unique sorted names",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Include nested subcomponents (default behavior for template and --list-parts)",
    )
    parser.add_argument(
        "--show-tree",
        action="store_true",
        help="Print assembly hierarchy tree from STEP labels",
    )
    parser.add_argument(
        "--top-level-only",
        action="store_true",
        help="Include only first-level components (disable nested subcomponent traversal)",
    )
    args = parser.parse_args()

    step_file = args.step_file or _resolve_default_step_file()
    if not step_file:
        parser.error(
            "step_file is required. Either pass a path, or place exactly one .stp/.step file in step_files/."
        )

    if args.show_tree:
        _print_tree(step_file, output=args.output)
        return

    # Default traversal is recursive; --top-level-only forces shallow mode.
    recursive_mode = args.recursive or (not args.top_level_only)

    if args.list_parts:
        _print_parts(step_file, unique=args.unique, output=args.output, recursive=recursive_mode)
        return

    out = write_constraints_template(step_file, args.output, recursive=recursive_mode)
    print(f"Wrote constraints template: {out}")


def _collect_components(root: Any, recursive: bool) -> list[str]:
    seq = TDF_LabelSequence()
    XCAFDoc_ShapeTool.GetComponents_s(root, seq)

    names: list[str] = []
    for i in range(1, seq.Length() + 1):
        child = seq.Value(i)
        names.append(_component_name(child))
        if recursive:
            recurse_target = _recurse_label(child)
            names.extend(_collect_components(recurse_target, recursive=True))
    return names


def _collect_tree_lines(root: Any, depth: int) -> list[str]:
    seq = TDF_LabelSequence()
    XCAFDoc_ShapeTool.GetComponents_s(root, seq)

    lines: list[str] = []
    for i in range(1, seq.Length() + 1):
        child = seq.Value(i)
        lines.append(f"{'  ' * depth}- {_component_name(child)}")
        recurse_target = _recurse_label(child)
        lines.extend(_collect_tree_lines(recurse_target, depth + 1))
    return lines


def _collect_hierarchy_nodes(root: Any, recursive: bool) -> list[dict[str, Any]]:
    seq = TDF_LabelSequence()
    XCAFDoc_ShapeTool.GetComponents_s(root, seq)

    nodes: list[dict[str, Any]] = []
    for i in range(1, seq.Length() + 1):
        child = seq.Value(i)
        child_node: dict[str, Any] = {"name": _component_name(child), "children": []}
        if recursive:
            recurse_target = _recurse_label(child)
            child_node["children"] = _collect_hierarchy_nodes(recurse_target, recursive=True)
        nodes.append(child_node)
    return nodes


def list_step_hierarchy_rows(step_path: str | Path, recursive: bool = True) -> list[dict[str, Any]]:
    """Return hierarchy as flat rows: [{"depth": int, "name": str}, ...]."""
    hierarchy = list_step_hierarchy(step_path, recursive=recursive)
    rows: list[dict[str, Any]] = []
    for node in hierarchy:
        rows.append({"depth": 0, "name": node["name"]})
        rows.extend(_hierarchy_to_rows(node["children"], depth=1))
    return rows


def _hierarchy_to_lines(nodes: list[dict[str, Any]], depth: int) -> list[str]:
    lines: list[str] = []
    for node in nodes:
        lines.append(f"{'\t' * depth}{node['name']}")
        lines.extend(_hierarchy_to_lines(node.get("children", []), depth + 1))
    return lines


def _hierarchy_to_rows(nodes: list[dict[str, Any]], depth: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for node in nodes:
        rows.append({"depth": depth, "name": node["name"]})
        rows.extend(_hierarchy_to_rows(node.get("children", []), depth + 1))
    return rows


def _component_name(component_label: Any) -> str:
    """Prefer component instance name, falling back to referred shape name."""
    comp_name = _label_name(component_label)
    if comp_name != "<unnamed>":
        return comp_name

    referred = TDF_Label()
    if XCAFDoc_ShapeTool.GetReferredShape_s(component_label, referred):
        ref_name = _label_name(referred)
        if ref_name != "<unnamed>":
            return ref_name
    return comp_name


def _recurse_label(component_label: Any) -> Any:
    """Recurse through referred assembly labels when available."""
    referred = TDF_Label()
    if XCAFDoc_ShapeTool.GetReferredShape_s(component_label, referred):
        if XCAFDoc_ShapeTool.IsAssembly_s(referred):
            return referred
    return component_label


def _resolve_default_step_file() -> str | None:
    """Return a default STEP path when there is exactly one obvious candidate."""
    candidates: list[Path] = []

    for pattern in ("step_files/*.stp", "step_files/*.step", "*.stp", "*.step"):
        candidates.extend(Path(".").glob(pattern))

    # Deduplicate while preserving order.
    unique: list[Path] = []
    seen: set[Path] = set()
    for item in candidates:
        resolved = item.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(item)

    if len(unique) == 1:
        return str(unique[0])
    return None


if __name__ == "__main__":
    main()
