import csv
import math
import os
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

from twin_lab.sdf_compiler import (
    NEUTRAL_VISUAL_RGB,
    PACKAGE_MARKER_NAME,
    compile_sdf_package,
    package_is_current,
)


def _write_triangle_obj(path: Path, x_offset: float = 0.0) -> None:
    path.write_text(
        f"v {x_offset} 0 0\nv {x_offset + 0.01} 0 0\nv {x_offset} 0.01 0\nf 1 2 3\n",
        encoding="utf-8",
    )


def test_compiles_portable_sdf_with_cad_relative_joint_limits(tmp_path: Path) -> None:
    fixed = tmp_path / "fixed.obj"
    moving = tmp_path / "moving.obj"
    attachment = tmp_path / "attachment.obj"
    environment = tmp_path / "environment.obj"
    _write_triangle_obj(fixed)
    _write_triangle_obj(moving, 0.02)
    _write_triangle_obj(attachment, 0.04)
    _write_triangle_obj(environment, 0.06)

    scene = {
        "schema": "slac-stage-cad-scene/v6",
        "instances": [],
        "motion_stage_meshes": {"A001": {"fixed": str(fixed), "moving": str(moving)}},
        "attachments": [{"parent_stage_ref": "A001", "mesh": str(attachment), "part_count": 1}],
        "static_geometry": [
            {
                "source_ref": "A100",
                "name": "Enclosure",
                "mesh": str(environment),
                "part_count": 1,
                "rgba": [0.95, 0.78, 0.12, 0.28],
            }
        ],
        "motion_chains": [
            {
                "name": "North Crystal",
                "joints": [
                    {
                        "key": "A001",
                        "ref": "A001",
                        "stack": "North Crystal",
                        "name": "rotation",
                        "joint_type": "revolute",
                        "fixed_role": "fixed",
                        "moving_role": "moving",
                        "axis_world": [0.0, 0.0, 1.0],
                        "origin_m": [0.1, 0.2, 0.3],
                        "limits": [math.radians(150.0), math.radians(210.0)],
                        "home": math.pi,
                        "cad_position": math.radians(170.0),
                    }
                ],
            }
        ],
    }
    scene_path = tmp_path / "scene.yaml"
    scene_path.write_text(yaml.safe_dump(scene, sort_keys=False), encoding="utf-8")

    sdf_path, archive_path = compile_sdf_package(
        scene_path,
        tmp_path / "package",
        model_name="test stack",
        include_collisions=True,
        archive=False,
    )

    assert archive_path is None
    root = ET.parse(sdf_path).getroot()
    assert root.attrib == {"version": "1.6"}
    assert root.find("model").attrib["name"] == "test_stack"
    assert len(root.findall("./model/link")) == 2
    assert any(
        "environment" in (visual.attrib.get("name") or "") for visual in root.findall(".//visual")
    )
    environment_visual = next(
        visual
        for visual in root.findall(".//visual")
        if "environment" in (visual.attrib.get("name") or "")
    )
    assert environment_visual.findtext("material/diffuse") == "0.95 0.78 0.12 0.28"
    base_joint = root.find("./model/joint[@type='fixed']")
    assert base_joint.findtext("parent") == "world"
    assert base_joint.findtext("child") == "assembly_base"
    joint = root.find("./model/joint[@type='revolute']")
    assert joint.findtext("parent") == "assembly_base"
    assert joint.findtext("pose") == "0.1 0.2 0.3 0 0 0"
    assert math.isclose(float(joint.findtext("axis/limit/lower")), -math.pi / 9.0)
    assert math.isclose(float(joint.findtext("axis/limit/upper")), 2.0 * math.pi / 9.0)

    visual_uris = [element.text for element in root.findall(".//visual/geometry/mesh/uri")]
    collision_uris = [element.text for element in root.findall(".//collision/geometry/mesh/uri")]
    assert visual_uris and collision_uris
    # Drake's Meshcat cannot render STL, so the canonical SDF must use OBJ visuals.
    assert all(not Path(uri).is_absolute() and uri.endswith(".obj") for uri in visual_uris)
    assert all(uri.endswith(".obj") for uri in collision_uris)

    matlab_root = ET.parse(sdf_path.with_name(f"{sdf_path.stem}_matlab.sdf")).getroot()
    matlab_visual_uris = [
        element.text for element in matlab_root.findall(".//visual/geometry/mesh/uri")
    ]
    assert all(uri.endswith(".stl") for uri in matlab_visual_uris)
    stl_path = sdf_path.parent / matlab_visual_uris[0]
    with stl_path.open("rb") as stream:
        stream.seek(80)
        assert struct.unpack("<I", stream.read(4))[0] == 1

    matlab_collision_uris = [
        element.text for element in matlab_root.findall(".//collision/geometry/mesh/uri")
    ]
    assert matlab_collision_uris
    assert all(uri.endswith(".stl") for uri in matlab_collision_uris)

    with (sdf_path.parent / "joint_metadata.csv").open(encoding="utf-8") as stream:
        metadata = next(csv.DictReader(stream))
    assert math.isclose(float(metadata["logical_home_offset"]), math.radians(170.0))
    assert (sdf_path.parent / "load_in_matlab.m").exists()


def test_default_package_is_a_visual_only_drake_and_matlab_pair(tmp_path: Path) -> None:
    mesh = tmp_path / "fixed.obj"
    _write_triangle_obj(mesh)
    scene_path = tmp_path / "scene.yaml"
    scene_path.write_text(
        yaml.safe_dump(
            {
                "schema": "slac-stage-cad-scene/v6",
                "instances": [{"ref": "A001", "model": "fixed", "mesh": str(mesh)}],
                "motion_stage_meshes": {},
                "attachments": [],
                "motion_chains": [],
            }
        ),
        encoding="utf-8",
    )

    sdf_path, _ = compile_sdf_package(scene_path, tmp_path / "package", archive=False)
    root = ET.parse(sdf_path).getroot()
    assert root.findall(".//visual")
    assert not root.findall(".//collision")
    # Drake needs OBJ visuals and MATLAB needs STL, so the default package is a matched pair
    # of visual-only SDFs rather than a single portable file.
    assert all(
        element.text.endswith(".obj") for element in root.findall(".//visual/geometry/mesh/uri")
    )
    matlab_path = sdf_path.with_name(f"{sdf_path.stem}_matlab.sdf")
    matlab_root = ET.parse(matlab_path).getroot()
    assert not matlab_root.findall(".//collision")
    assert all(
        element.text.endswith(".stl")
        for element in matlab_root.findall(".//visual/geometry/mesh/uri")
    )
    loader = (sdf_path.parent / "load_in_matlab.m").read_text(encoding="utf-8")
    assert "sdfFile" in loader
    assert matlab_path.name in loader


def test_refuses_to_replace_an_unmanaged_output_directory(tmp_path: Path) -> None:
    scene_path = tmp_path / "scene.yaml"
    scene_path.write_text(
        yaml.safe_dump(
            {
                "schema": "slac-stage-cad-scene/v6",
                "instances": [],
                "motion_stage_meshes": {},
                "attachments": [],
                "motion_chains": [],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "existing"
    output.mkdir()
    (output / "user-file.txt").write_text("keep", encoding="utf-8")

    try:
        compile_sdf_package(scene_path, output, archive=False)
    except FileExistsError:
        pass
    else:
        raise AssertionError("Expected unmanaged output-directory protection")
    assert (output / "user-file.txt").read_text(encoding="utf-8") == "keep"


def test_neutral_visuals_drop_the_review_colours_but_keep_transparency(tmp_path: Path) -> None:
    mesh = tmp_path / "shell.obj"
    _write_triangle_obj(mesh)
    scene_path = tmp_path / "scene.yaml"
    scene_path.write_text(
        yaml.safe_dump(
            {
                "schema": "slac-stage-cad-scene/v6",
                "instances": [],
                "motion_stage_meshes": {},
                "attachments": [],
                "motion_chains": [],
                "static_geometry": [
                    {
                        "source_ref": "A037",
                        "name": "Enclosure",
                        "mesh": str(mesh),
                        "part_count": 1,
                        "rgba": [0.95, 0.78, 0.12, 0.28],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    sdf_path, _ = compile_sdf_package(
        scene_path, tmp_path / "package", neutral_visuals=True, archive=False
    )

    diffuse = ET.parse(sdf_path).getroot().findtext(".//visual/material/diffuse")
    red, green, blue, alpha = (float(value) for value in diffuse.split())
    assert (red, green, blue) == NEUTRAL_VISUAL_RGB
    # The enclosure has to stay see-through or the highlights inside it are invisible.
    assert alpha == 0.28
    assert not package_is_current(tmp_path / "package", scene_path)
    assert package_is_current(tmp_path / "package", scene_path, neutral_visuals=True)


def test_package_is_stale_when_the_review_or_its_meshes_change(tmp_path: Path) -> None:
    mesh = tmp_path / "fixed.obj"
    _write_triangle_obj(mesh)
    inventory = tmp_path / "stack.inventory.yaml"

    def write_inventory(threshold: float) -> None:
        inventory.write_text(
            yaml.safe_dump(
                {"decomposition": {"overrides": [{"refs": ["P650"], "threshold": threshold}]}}
            ),
            encoding="utf-8",
        )

    write_inventory(0.05)
    scene_path = tmp_path / "scene.yaml"
    scene_path.write_text(
        yaml.safe_dump(
            {
                "schema": "slac-stage-cad-scene/v6",
                "source_inventory": str(inventory),
                "instances": [{"ref": "A001", "model": "fixed", "mesh": str(mesh)}],
                "motion_stage_meshes": {},
                "attachments": [],
                "motion_chains": [],
            }
        ),
        encoding="utf-8",
    )
    package = tmp_path / "package"

    compile_sdf_package(scene_path, package, archive=False)
    assert package_is_current(package, scene_path)
    assert not package_is_current(package, scene_path, collision_mode="convex")

    write_inventory(0.01)
    assert not package_is_current(package, scene_path)

    write_inventory(0.05)
    assert package_is_current(package, scene_path)

    stamped = (package / PACKAGE_MARKER_NAME).stat().st_mtime_ns
    os.utime(mesh, ns=(stamped + 1, stamped + 1))
    assert not package_is_current(package, scene_path)


def test_add_mesh_geometry_declares_convex_only_when_requested():
    import xml.etree.ElementTree as ET

    from twin_lab.sdf_compiler import _add_mesh_geometry

    plain = ET.Element("collision")
    _add_mesh_geometry(plain, "meshes/a048.obj")
    assert plain.find("geometry/mesh/uri").text == "meshes/a048.obj"
    assert [child.tag for child in plain.find("geometry/mesh")] == ["uri", "scale"]

    convex = ET.Element("collision")
    _add_mesh_geometry(convex, "meshes/a048_p901_003.obj", declare_convex=True)
    assert "drake:declare_convex" in [child.tag for child in convex.find("geometry/mesh")]


def test_compile_sdf_package_rejects_an_unknown_collision_mode(tmp_path):
    import pytest

    from twin_lab.sdf_compiler import compile_sdf_package

    with pytest.raises(ValueError, match="collision_mode"):
        compile_sdf_package(tmp_path / "scene.yaml", tmp_path / "out", collision_mode="vhacd")
