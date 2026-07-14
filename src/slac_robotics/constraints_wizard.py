"""Utilities to bootstrap joint-constraint configs from assembly STEP files.

Run:
    python -m slac_robotics.constraints_wizard step_files/your_assembly.stp
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDF import TDF_Label, TDF_LabelSequence
from OCP.TDataStd import TDataStd_Name
from OCP.TDocStd import TDocStd_Document
from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool


def list_step_components(step_path: str | Path) -> list[str]:
    """Return first-level component names from an assembly STEP file."""
    path = Path(step_path)
    if not path.exists():
        raise FileNotFoundError(f"STEP file not found: {path}")

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
        seq = TDF_LabelSequence()
        XCAFDoc_ShapeTool.GetComponents_s(root, seq)
        for j in range(1, seq.Length() + 1):
            components.append(_label_name(seq.Value(j)))

    return components


def write_constraints_template(step_path: str | Path, output_path: str | Path | None = None) -> Path:
    """Write a JSON constraints template beside the STEP file."""
    step = Path(step_path)
    component_names = list_step_components(step)
    if not component_names:
        raise ValueError("No assembly components were discovered in the STEP file")

    deduped = _dedupe_names(component_names)
    template = {
        "assembly_step": str(step),
        "notes": [
            "Set base_components to fixed structure that does not move.",
            "Create one entry per motorized axis in joints.",
            "Each joint components list should include all parts that move together on that axis.",
            "Units: meters for limits_m and home_m.",
        ],
        "base_components": [],
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
        "available_components": deduped,
    }

    out = Path(output_path) if output_path else step.with_suffix(".constraints.json")
    out.write_text(json.dumps(template, indent=2), encoding="utf-8")
    return out


def _label_name(label: TDF_Label) -> str:
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


def _print_parts(step_file: str, unique: bool, output: str | None) -> None:
    parts = list_step_components(step_file)
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
        help="Print part names from first-level assembly components instead of writing template",
    )
    parser.add_argument(
        "--unique",
        action="store_true",
        help="With --list-parts, print unique sorted names",
    )
    args = parser.parse_args()

    step_file = args.step_file or _resolve_default_step_file()
    if not step_file:
        parser.error(
            "step_file is required. Either pass a path, or place exactly one .stp/.step file in step_files/."
        )

    if args.list_parts:
        _print_parts(step_file, unique=args.unique, output=args.output)
        return

    out = write_constraints_template(step_file, args.output)
    print(f"Wrote constraints template: {out}")


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
