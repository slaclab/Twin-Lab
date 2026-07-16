import csv
import math
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

from slac_robotics.sdf_compiler import compile_sdf_package


def _write_triangle_obj(path: Path, x_offset: float = 0.0) -> None:
    path.write_text(
        f"v {x_offset} 0 0\nv {x_offset + 0.01} 0 0\nv {x_offset} 0.01 0\nf 1 2 3\n",
        encoding="utf-8",
    )


def test_compiles_portable_sdf_with_home_relative_joint_limits(tmp_path: Path) -> None:
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
    assert math.isclose(float(joint.findtext("axis/limit/lower")), -math.pi / 6.0)
    assert math.isclose(float(joint.findtext("axis/limit/upper")), math.pi / 6.0)

    visual_uris = [element.text for element in root.findall(".//visual/geometry/mesh/uri")]
    collision_uris = [element.text for element in root.findall(".//collision/geometry/mesh/uri")]
    assert visual_uris and collision_uris
    assert all(not Path(uri).is_absolute() and uri.endswith(".stl") for uri in visual_uris)
    assert all(uri.endswith(".obj") for uri in collision_uris)
    stl_path = sdf_path.parent / visual_uris[0]
    with stl_path.open("rb") as stream:
        stream.seek(80)
        assert struct.unpack("<I", stream.read(4))[0] == 1

    matlab_root = ET.parse(sdf_path.with_name(f"{sdf_path.stem}_matlab.sdf")).getroot()
    matlab_collision_uris = [
        element.text for element in matlab_root.findall(".//collision/geometry/mesh/uri")
    ]
    assert matlab_collision_uris
    assert all(uri.endswith(".stl") for uri in matlab_collision_uris)

    with (sdf_path.parent / "joint_metadata.csv").open(encoding="utf-8") as stream:
        metadata = next(csv.DictReader(stream))
    assert math.isclose(float(metadata["logical_home_offset"]), math.pi)
    assert (sdf_path.parent / "load_in_matlab.m").exists()


def test_default_package_is_one_portable_visual_only_sdf(tmp_path: Path) -> None:
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
    assert not sdf_path.with_name(f"{sdf_path.stem}_matlab.sdf").exists()
    assert "sdfFile" in (sdf_path.parent / "load_in_matlab.m").read_text(encoding="utf-8")


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
