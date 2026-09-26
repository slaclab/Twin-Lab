from __future__ import annotations

import json
from pathlib import Path

import yaml

from twin_lab.constraints_wizard import _build_manifest_ref_map, remap_stage_inventory
from twin_lab.update_43841_step import validate_review_identity


def test_refresh_preflight_rejects_stale_stage_and_attachment_refs() -> None:
    manifest = {"occurrences": [
        {"ref": "A001", "id": "root/stack", "name": "stack"},
        {"ref": "A002", "id": "root/stack/stage", "name": "LIB-NEW"},
        {"ref": "P001", "id": "root/stack/bracket", "name": "bracket"},
        {"ref": "P002", "id": "root/other/bracket", "name": "bracket"},
    ]}
    review = {
        "subassembly": {"ref": "A001", "name": "stack"},
        "stage_instances": [{"ref": "A002", "catalog": "motor"}],
        "static_geometry": [],
        "attachment_overrides": {"moving": {"A002": ["P001"]}},
    }
    assert validate_review_identity(review, manifest) == []
    review["attachment_overrides"]["moving"]["A002"].append("P002")
    assert validate_review_identity(review, manifest) == []
    previous = {"occurrences": [dict(item) for item in manifest["occurrences"]]}
    manifest["occurrences"][3]["name"] = "wrong bracket"
    assert "attachment P002 on A002 changed identity" in validate_review_identity(
        review, manifest, previous
    )
    manifest["occurrences"][1]["name"] = "unrelated"
    assert any("stage A002" in issue for issue in validate_review_identity(review, manifest))


def test_refresh_preflight_uses_old_identity_when_refs_shift() -> None:
    previous = {"occurrences": [
        {"ref": "A001", "name": "stack", "id": "root/stack"},
        {"ref": "A002", "name": "LIB-A", "id": "root/stack/stage"},
        {"ref": "P001", "name": "adapter", "id": "root/stack/adapter"},
    ]}
    current = {"occurrences": [
        {"ref": "A003", "name": "stack", "id": "root/stack"},
        {"ref": "A004", "name": "LIB-A", "id": "root/stack/stage"},
        {"ref": "P002", "name": "adapter", "id": "root/stack/adapter"},
    ]}
    review = {
        "subassembly": {"ref": "A003", "name": "stack"},
        "stage_instances": [{"ref": "A004", "catalog": "motor"}],
        "attachment_overrides": {"moving": {"A004": ["P002"]}},
    }
    ref_map = {"A001": "A003", "A002": "A004", "P001": "P002"}
    assert validate_review_identity(review, current, previous, ref_map) == []
    current["occurrences"][1]["name"] = "LIB-OTHER"
    assert any("stage A004 changed identity" in issue for issue in validate_review_identity(
        review, current, previous, ref_map
    ))


def test_old_alias_does_not_swap_cameras_after_another_revision() -> None:
    def occurrence(ref: str, index: int, x: float) -> dict:
        return {
            "ref": ref, "id": f"root/{index}:camera", "name": "camera",
            "parent_id": "root", "depth": 1, "is_assembly": True,
            "transform_to_parent": [[1, 0, 0, x], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
        }

    old = {"occurrences": [occurrence("A191", 6, 105), occurrence("A192", 7, -315)]}
    new = {"occurrences": [occurrence("A191", 6, 105.062), occurrence("A192", 7, -315)]}
    aliases = {"occurrence_id_aliases": {"root/6:camera": "root/7:camera"}, "name_aliases": {}}
    mapped, _ = _build_manifest_ref_map(old, new, aliases)
    assert mapped == {"A191": "A191", "A192": "A192"}
    new["occurrences"][0]["transform_to_parent"][0][3] = -315
    mapped, _ = _build_manifest_ref_map(old, new, aliases)
    assert mapped["A191"] == "A192"


def test_remaps_inventory_with_name_aliases(tmp_path: Path) -> None:
    previous_manifest = tmp_path / "previous-manifest.json"
    new_manifest = tmp_path / "new-manifest.json"
    inventory = tmp_path / "review.inventory.yaml"
    alias_map = tmp_path / "aliases.yaml"

    previous_manifest.write_text(
        json.dumps(
            {
                "occurrences": [
                    {
                        "ref": "A001",
                        "id": "root[1]/root",
                        "name": "root",
                        "parent_id": None,
                        "depth": 0,
                        "is_assembly": True,
                    },
                    {
                        "ref": "A002",
                        "id": "root[1]/root/1:OLD-STACK",
                        "name": "OLD-STACK",
                        "parent_id": "root[1]/root",
                        "depth": 1,
                        "is_assembly": True,
                    },
                    {
                        "ref": "A003",
                        "id": "root[1]/root/1:OLD-STACK/4:LIB-OLD-Z",
                        "name": "LIB-OLD-Z",
                        "parent_id": "root[1]/root/1:OLD-STACK",
                        "depth": 2,
                        "is_assembly": True,
                    },
                    {
                        "ref": "A004",
                        "id": "root[1]/root/1:OLD-STACK/5:LIB-OLD-XY",
                        "name": "LIB-OLD-XY",
                        "parent_id": "root[1]/root/1:OLD-STACK",
                        "depth": 2,
                        "is_assembly": True,
                    },
                    {
                        "ref": "P001",
                        "id": "root[1]/root/1:OLD-STACK/5:LIB-OLD-XY/1:PART-OLD",
                        "name": "PART-OLD",
                        "parent_id": "root[1]/root/1:OLD-STACK/5:LIB-OLD-XY",
                        "depth": 3,
                        "is_assembly": False,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    new_manifest.write_text(
        json.dumps(
            {
                "occurrences": [
                    {
                        "ref": "A010",
                        "id": "root[1]/root",
                        "name": "root",
                        "parent_id": None,
                        "depth": 0,
                        "is_assembly": True,
                    },
                    {
                        "ref": "A011",
                        "id": "root[1]/root/9:NEW-STACK",
                        "name": "NEW-STACK",
                        "parent_id": "root[1]/root",
                        "depth": 1,
                        "is_assembly": True,
                    },
                    {
                        "ref": "A012",
                        "id": "root[1]/root/9:NEW-STACK/2:LIB-NEW-Z",
                        "name": "LIB-NEW-Z",
                        "parent_id": "root[1]/root/9:NEW-STACK",
                        "depth": 2,
                        "is_assembly": True,
                    },
                    {
                        "ref": "A013",
                        "id": "root[1]/root/9:NEW-STACK/7:LIB-NEW-XY",
                        "name": "LIB-NEW-XY",
                        "parent_id": "root[1]/root/9:NEW-STACK",
                        "depth": 2,
                        "is_assembly": True,
                    },
                    {
                        "ref": "P010",
                        "id": "root[1]/root/9:NEW-STACK/7:LIB-NEW-XY/1:PART-NEW",
                        "name": "PART-NEW",
                        "parent_id": "root[1]/root/9:NEW-STACK/7:LIB-NEW-XY",
                        "depth": 3,
                        "is_assembly": False,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    inventory.write_text(
        """schema: slac-stage-inventory/v1
source_step: cad/example/source.stp
cad_manifest: cad/example/manifest.json
subassembly:
  ref: A002
  name: OLD-STACK
  occurrence_count: 4
  assembly_count: 3
  leaf_part_count: 1
stage_instances:
  - {ref: A003, library_id: LIB-OLD-Z, catalog: z_stage}
  - {ref: A004, library_id: LIB-OLD-XY, catalog: xy_stage}
compound_motion_chains:
  Example:
    - {key: A003:z, stage_ref: A003, fixed_role: fixed, moving_role: moving,
       name: z, axis_local: [0, 0, 1], limits: [-0.001, 0.001]}
    - {key: A004:x, stage_ref: A004, moving_role: x,
       name: x, axis_local: [1, 0, 0], limits: [-0.001, 0.001]}
attachment_overrides:
  moving:
    A004: [P001]
reviewed_connections:
  - [P001, A004]
""",
        encoding="utf-8",
    )
    alias_map.write_text(
        yaml.safe_dump(
            {
                "name_aliases": {
                    "OLD-STACK": "NEW-STACK",
                    "LIB-OLD-Z": "LIB-NEW-Z",
                    "LIB-OLD-XY": "LIB-NEW-XY",
                    "PART-OLD": "PART-NEW",
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    output, report = remap_stage_inventory(
        inventory,
        previous_manifest_path=previous_manifest,
        new_manifest_path=new_manifest,
        alias_map_path=alias_map,
    )

    text = output.read_text(encoding="utf-8")
    assert report["unresolved_refs"] == []
    assert f"cad_manifest: {new_manifest.relative_to(tmp_path).as_posix()}" not in text
    assert "cad_manifest: " + new_manifest.as_posix() in text
    assert "ref: A011" in text
    assert "A012:z" in text
    assert "A013:x" in text
    assert "A013: [P010]" in text
    assert "occurrence_count: 4" in text
    assert "assembly_count: 3" in text
    assert "leaf_part_count: 1" in text


def test_remaps_four_digit_part_refs(tmp_path: Path) -> None:
    previous_manifest = tmp_path / "previous-manifest.json"
    new_manifest = tmp_path / "new-manifest.json"
    inventory = tmp_path / "review.inventory.yaml"

    def manifest(assembly_ref: str, part_ref: str) -> str:
        return json.dumps(
            {
                "occurrences": [
                    {
                        "ref": "A001",
                        "id": "root[1]/root",
                        "name": "root",
                        "parent_id": None,
                        "depth": 0,
                        "is_assembly": True,
                    },
                    {
                        "ref": assembly_ref,
                        "id": "root[1]/root/1:STACK",
                        "name": "STACK",
                        "parent_id": "root[1]/root",
                        "depth": 1,
                        "is_assembly": True,
                    },
                    {
                        "ref": part_ref,
                        "id": "root[1]/root/1:STACK/1:PART",
                        "name": "PART",
                        "parent_id": "root[1]/root/1:STACK",
                        "depth": 2,
                        "is_assembly": False,
                    },
                ]
            }
        )

    previous_manifest.write_text(manifest("A1002", "P1019"), encoding="utf-8")
    new_manifest.write_text(manifest("A1003", "P0998"), encoding="utf-8")
    inventory.write_text(
        """schema: slac-stage-inventory/v1
source_step: cad/example/source.stp
cad_manifest: cad/example/manifest.json
subassembly:
  ref: A1002
  name: STACK
  occurrence_count: 2
  assembly_count: 1
  leaf_part_count: 1
hidden_occurrences:
  - P1019
""",
        encoding="utf-8",
    )

    output, report = remap_stage_inventory(
        inventory,
        previous_manifest_path=previous_manifest,
        new_manifest_path=new_manifest,
    )

    text = output.read_text(encoding="utf-8")
    assert report["unresolved_refs"] == []
    assert "ref: A1003" in text
    assert "- P0998" in text
    assert "P1019" not in text
