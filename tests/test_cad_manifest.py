from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytest.importorskip("OCP")

from twin_lab.cad_motion import prepare_motion_setup  # noqa: E402
from twin_lab.constraints_wizard import (  # noqa: E402
    _default_kinematics_path,
    _default_manifest_path,
    _default_preview_path,
    _outputs_are_fresh,
    check_kinematics_review,
    extract_cad_manifest,
    status_lines,
    write_kinematics_template,
    write_step_preview,
)
from twin_lab.static_review import (
    carry_review,
    collision_only_refs,
    collision_refs,
    normalized_name,
    prepare_collision_meshes,
    review_cache_name,
    review_selection,
    select_leaves,
)


def test_cad_project_defaults_keep_generated_files_out_of_source_directories() -> None:
    source = Path("cad/DSG-000040389/source.stp")
    manifest = Path("cad/DSG-000040389/manifest.json")

    assert _default_manifest_path(source) == manifest
    assert _default_kinematics_path(manifest) == Path("cad/DSG-000040389/reviews/kinematics.yaml")
    assert (
        _default_preview_path(source, "A035")
        .as_posix()
        .endswith(".cache/twin_lab/previews/DSG-000040389/preview.A035.gltf")
    )


def test_detects_fresh_cached_outputs(tmp_path: Path) -> None:
    source = tmp_path / "assembly.stp"
    output = tmp_path / "assembly.preview.gltf"
    source.write_text("source", encoding="utf-8")
    output.write_text("preview", encoding="utf-8")

    os.utime(output, ns=(1_000_000_000, 1_000_000_000))
    os.utime(source, ns=(2_000_000_000, 2_000_000_000))
    assert not _outputs_are_fresh(source, [output])

    os.utime(output, ns=(3_000_000_000, 3_000_000_000))
    assert _outputs_are_fresh(source, [output])


def test_extracts_stable_occurrence_manifest() -> None:
    manifest = extract_cad_manifest("cad/DSG-000046520/source.stp")
    occurrences = manifest["occurrences"]

    assert manifest["schema"] == "slac-cad-manifest/v1"
    assert manifest["length_unit"] == "millimeter"
    assert len(occurrences) == 14
    assert len({item["id"] for item in occurrences}) == len(occurrences)
    assert len({item["ref"] for item in occurrences}) == len(occurrences)
    assert sum(item["ref"].startswith("P") for item in occurrences) == 10
    assert all(len(item["transform_to_parent"]) == 4 for item in occurrences)
    assert any(item["name"] == "DSG-000046522" for item in occurrences)


def test_writes_small_human_review_template(tmp_path: Path) -> None:
    manifest_path = tmp_path / "assembly.cad.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema": "slac-cad-manifest/v1",
                "occurrences": [
                    {"ref": "A001", "name": "assembly", "depth": 0, "is_assembly": True},
                    {"ref": "P001", "name": "base", "depth": 1, "is_assembly": False},
                    {"ref": "P002", "name": "carriage", "depth": 1, "is_assembly": False},
                ],
            }
        ),
        encoding="utf-8",
    )

    output = write_kinematics_template(manifest_path)
    text = output.read_text(encoding="utf-8")

    assert "schema: slac-kinematics-review/v1" in text
    assert "P001" in text
    assert "occurrences: []" in text
    assert "type: prismatic" in text

    status = check_kinematics_review(output)
    assert status["part_count"] == 2
    assert status["unassigned"] == ["P001", "P002"]
    assert any("Parts assigned:   0/2" in line for line in status_lines(status))


def test_writes_browser_preview(tmp_path: Path) -> None:
    output = write_step_preview(
        "cad/DSG-000046520/source.stp",
        tmp_path / "assembly.gltf",
        linear_deflection_mm=1.0,
        focus_refs=["A003", "A004"],
    )

    assert output.exists()
    assert output.with_suffix(".bin").exists()
    assert output.stat().st_size > 0


def test_writes_preview_without_omitted_leaves(tmp_path: Path) -> None:
    output = write_step_preview(
        "cad/DSG-000046520/source.stp", tmp_path / "selected.gltf", omit_refs={"P001"}
    )
    assert output.exists()
    assert output.with_suffix(".bin").stat().st_size > 0
    with pytest.raises(ValueError, match="Unknown omitted"):
        write_step_preview(
            "cad/DSG-000046520/source.stp", tmp_path / "bad.gltf", omit_refs={"P999"}
        )


def test_static_review_omits_named_parts(tmp_path: Path) -> None:
    manifest = extract_cad_manifest("cad/DSG-000046520/source.stp")
    omitted, total = select_leaves(manifest, {normalized_name("REF-000221282"): ["old omit"]})
    assert total == 10
    assert omitted == {"P001"}
    output = write_step_preview(
        "cad/DSG-000046520/source.stp", tmp_path / "selected.gltf", omit_refs=omitted
    )
    assert output.with_suffix(".bin").stat().st_size > 0


def test_static_review_filters_assembly_descendants_and_separates_enclosure() -> None:
    manifest = {
        "occurrences": [
            {"id": "root", "name": "root", "ref": "A001", "is_assembly": True},
            {"id": "root/box", "name": "enclosure", "ref": "A002", "is_assembly": True},
            {"id": "root/box/shell", "name": "shell", "ref": "P001", "is_assembly": False},
            {"id": "root/box/cover", "name": "front cover", "ref": "P002", "is_assembly": False},
            {"id": "root/camera", "name": "camera", "ref": "A003", "is_assembly": True},
            {"id": "root/camera/lens", "name": "lens", "ref": "P003", "is_assembly": False},
            {"id": "root/bolt", "name": "M4 bolt", "ref": "P004", "is_assembly": False},
            {"id": "root/target", "name": "target", "ref": "P005", "is_assembly": False},
        ]
    }
    omitted, translucent, total = review_selection(manifest, {
        "omitted_names": {}, "omit_fasteners": True, "omitted_assemblies": ["camera"],
        "omitted_components": ["front cover"], "translucent_assemblies": ["enclosure"],
    })
    assert (omitted, translucent, total) == ({"P002", "P003", "P004"}, {"P001"}, 5)


def test_static_review_omits_unlabelled_studs_and_thumb_nuts() -> None:
    names = [
        "PEM__SelfClinchingStud_FlushHd_.250-20x.50L_SST__FHS-0420-8",
        "McMasterCarr__NutThumbBrassFlangedKnurledHd4-40__92741A100",
    ]
    manifest = {
        "occurrences": [
            {"id": f"root/{index}", "name": name, "ref": f"P{index:03}", "is_assembly": False}
            for index, name in enumerate(names, 1)
        ]
    }
    omitted, translucent, total = review_selection(
        manifest, {"omitted_names": {}, "omit_fasteners": True}
    )
    assert (omitted, translucent, total) == ({"P001", "P002"}, set(), 2)


def test_static_review_tints_only_named_chamber_panels() -> None:
    manifest = {"occurrences": [
        {"id": "chamber/panel", "name": "chamber wall", "ref": "P001", "is_assembly": False},
        {"id": "chamber/optic", "name": "optic", "ref": "P002", "is_assembly": False},
    ]}
    omitted, translucent, total = review_selection(
        manifest, {"omitted_names": {}, "translucent_components": ["chamber wall"]}
    )
    assert (omitted, translucent, total) == (set(), {"P001"}, 2)


def test_static_review_scopes_duplicate_parts_by_parent_and_pose() -> None:
    manifest = {"occurrences": [
        {"id": "root", "name": "root", "ref": "A001", "is_assembly": True},
        {"id": "root/left", "name": "left", "ref": "A002", "is_assembly": True},
        {"id": "root/right", "name": "right", "ref": "A003", "is_assembly": True},
        *[
            {
                "id": f"root/left/{index}", "parent_id": "root/left", "name": "post",
                "ref": f"P{index:03}", "is_assembly": False,
                "transform_to_parent": [
                    [1, 0, 0, distance], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]
                ],
            }
            for index, distance in ((1, 10.0), (2, 40.0))
        ],
        {
            "id": "root/right/post", "parent_id": "root/right", "name": "post",
            "ref": "P003", "is_assembly": False,
            "transform_to_parent": [[1, 0, 0, 10], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
        },
    ]}
    recipe = {
        "omitted_names": {},
        "omitted_placed_components": [
            {"parent": "left", "name": "post", "translation_mm": [10, 0, 0], "tolerance_mm": 2}
        ],
    }
    omitted, _, _ = review_selection(manifest, recipe)
    assert omitted == {"P001"}
    manifest["occurrences"][3]["transform_to_parent"][0][3] = 20
    with pytest.raises(ValueError, match="Expected one placed post under left, found 0"):
        review_selection(manifest, recipe)


def test_collision_only_cover_is_not_visible_but_still_collides() -> None:
    manifest = {"occurrences": [
        {"id": "root", "name": "root", "ref": "A001", "is_assembly": True},
        {"id": "root/cover", "name": "cover", "ref": "A002", "is_assembly": True},
        {"id": "root/cover/panel", "name": "panel", "ref": "P001", "is_assembly": False},
        {"id": "root/optic", "name": "optic", "ref": "P002", "is_assembly": False},
    ]}
    recipe = {"omitted_names": {}, "collision_only_assemblies": ["cover"]}
    omitted, _, _ = review_selection(manifest, recipe)
    assert omitted == collision_only_refs(manifest, recipe) == {"P001"}
    assert collision_refs(manifest, recipe) == {"P001", "P002"}


def test_carry_review_preserves_hidden_cover_and_removes_disappeared_parts(tmp_path: Path) -> None:
    step = tmp_path / "next.stp"
    step.write_bytes(b"next revision")
    old = {"occurrences": [
        {"name": "root", "is_assembly": True},
        {"name": "cover_oa_1", "is_assembly": True},
        {"name": "removed", "is_assembly": False},
    ]}
    new = {"occurrences": [
        {"id": "root", "ref": "A001", "name": "root", "is_assembly": True},
        {"id": "root/cover", "ref": "A002", "name": "cover_oa_99", "is_assembly": True},
        {"id": "root/cover/panel", "ref": "P010", "name": "panel", "is_assembly": False},
        {"id": "root/new", "ref": "P011", "name": "new optic", "is_assembly": False},
    ]}
    recipe = {
        "source_sha256": "old", "omitted_names": {"removed": ["obsolete"]},
        "collision_only_assemblies": ["cover_oa_1"], "translucent_components": ["removed"],
    }
    carried, added = carry_review(old, new, recipe, step)
    assert carried["omitted_names"] == {}
    assert carried["translucent_components"] == []
    assert collision_only_refs(new, carried) == {"P010"}
    assert added == ["new optic", "panel"]


def test_carry_review_reports_new_occurrences_of_known_names(tmp_path: Path) -> None:
    step = tmp_path / "next.stp"
    step.write_bytes(b"next revision")
    old = {"occurrences": [{"name": "same", "is_assembly": False}]}
    new = {"occurrences": [
        {"ref": f"P{i:03}", "id": f"root/{i}", "name": "same", "is_assembly": False}
        for i in (1, 2, 3)
    ]}
    carried, added = carry_review(old, new, {"omitted_names": {}}, step)
    assert carried["omitted_names"] == {}
    assert added == ["same", "same"]


def test_new_assembly_review_uses_distinct_cache(tmp_path: Path) -> None:
    assert review_cache_name(tmp_path / "other-assembly.yaml") != "43841-static-review"


def test_collision_meshes_keep_hidden_cover_as_separate_source(tmp_path: Path) -> None:
    from twin_lab.convex_collision import read_part_refs

    step = Path("cad/DSG-000046520/source.stp")
    manifest = extract_cad_manifest(step)
    recipe = {
        "source_sha256": "fixture",
        "omitted_names": {},
        "collision_only_assemblies": ["REF-000221283"],
    }
    sources = prepare_collision_meshes(step, manifest, recipe, output_dir=tmp_path)
    assert [source.name for source in sources] == ["batch_000.obj", "collision_only_cover.obj"]
    assert set(read_part_refs(sources[1])) == {"P001", "P002"}
    assert "P001" not in read_part_refs(sources[0])


def test_prepares_provisional_real_cad_motion_groups() -> None:
    setup = prepare_motion_setup(
        "cad/DSG-000046520/reviews/polycap-stack.kinematics.yaml",
        linear_deflection_mm=1.0,
    )

    assert set(setup.meshes) == {"base", "x_carriage", "y_carriage", "z_carriage"}
    assert all(path.exists() and path.stat().st_size > 0 for path in setup.meshes.values())
    assert [joint.name for joint in setup.joints] == ["z", "y", "x"]
    assert setup.joints[0].limits_m == (-0.004, 0.004)
    assert setup.joints[2].limits_m == (-0.005, 0.005)
    assert setup.model_origin_ref == "P007"
    assert setup.model_origin_m == pytest.approx((-0.1205, -0.1685, 0.1000), abs=0.002)
