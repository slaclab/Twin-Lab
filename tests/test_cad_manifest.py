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
