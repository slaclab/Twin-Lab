import json
import math
from pathlib import Path

import yaml

from slac_robotics.stage_cad_viewer import (
    _is_fastener_name,
    _joint_displacement,
    _joint_origin_m,
    _reviewed_home,
    _reviewed_limits,
    _rotate_vector,
    _transform_data,
)


def test_43841_inventory_uses_reusable_stage_catalog() -> None:
    catalog = yaml.safe_load(Path("config/stage-catalog.yaml").read_text(encoding="utf-8"))
    inventory = yaml.safe_load(
        Path("cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml").read_text(
            encoding="utf-8"
        )
    )
    manifest = json.loads(Path("cad/DSG-000040389/manifest.json").read_text(encoding="utf-8"))

    stages = catalog["stages"]
    instances = inventory["stage_instances"]
    references = [instance["ref"] for instance in instances]

    assert inventory["subassembly"]["ref"] == "A035"
    assert len(instances) == 19
    assert len(references) == len(set(references))
    assert all(instance["catalog"] in stages for instance in instances)

    occurrences = {item["ref"]: item for item in manifest["occurrences"]}
    root_id = occurrences[inventory["subassembly"]["ref"]]["id"]
    assert all(occurrences[ref]["is_assembly"] for ref in references)
    assert all(occurrences[ref]["id"].startswith(f"{root_id}/") for ref in references)

    static_geometry = inventory["static_geometry"]
    assert [item["ref"] for item in static_geometry] == [
        "A034",
        "A026",
        "A027",
        "P1173",
        "A020",
        "A004",
        "A003",
    ]
    assert all(item["ref"] in occurrences for item in static_geometry)
    assert static_geometry[0]["rgba"] == [0.95, 0.78, 0.12, 0.28]
    assert static_geometry[3]["rgba"] == [0.20, 0.65, 0.95, 0.35]

    visual_styles = inventory["visual_styles"]
    stage_catalogs = {instance["catalog"] for instance in instances}
    assert set(visual_styles["stage_models"]) == stage_catalogs
    styled_attachment_refs = {
        ref for style in visual_styles["attachment_groups"].values() for ref in style["refs"]
    }
    reviewed_attachment_refs = set(inventory["attachment_overrides"]["fixed"])
    reviewed_attachment_refs.update(
        ref for refs in inventory["attachment_overrides"]["moving"].values() for ref in refs
    )
    assert styled_attachment_refs == reviewed_attachment_refs
    assert visual_styles["attachment_groups"]["crystal_and_holder"]["refs"] == [
        "P886",
        "P889",
        "P890",
        "P891",
        "P893",
        "P894",
        "P895",
        "P909",
        "P955",
        "P956",
        "P957",
        "P1012",
    ]
    assert visual_styles["attachment_groups"]["polycap_and_holder"]["refs"] == [
        "P1028",
        "P1029",
        "P1072",
        "P1073",
        "P1107",
        "P1108",
    ]
    assert visual_styles["attachment_groups"]["detector_adapter"]["refs"] == ["P803"]
    assert visual_styles["attachment_groups"]["detector"]["refs"] == ["P802"]

    detector_stage = stages["micronix_vt_50l_c0014"]
    assert detector_stage["manufacturer"] == "MICRONIX USA"
    assert detector_stage["model"] == "VT-50L-C0014"
    assert detector_stage["axis_local"] == [0.0, 1.0, 0.0]
    assert detector_stage["component_roles"] == {"fixed": [2], "moving": [1]}
    assert detector_stage["limits"] == [-0.2, 0.2]

    assert stages["kohzu_sxa0530_r01_bm"]["limits"] == [-0.015, 0.015]
    assert stages["kohzu_sxa0750_r01_r_bm"]["limits"] == [-0.025, 0.025]
    assert stages["kohzu_sxa0750_r01_r_bm"]["mirrored"] is True
    assert stages["kohzu_sa04b_rt02_bm"]["pivot_offset_local"] == [0.0, 0.0, 0.057]
    assert stages["kohzu_sa04b_rt02_r_bm"]["pivot_offset_local"] == [0.0, 0.0, 0.057]

    assert inventory["hidden_occurrences"] == ["P772", "P773", "P774"]
    assert inventory["attachment_overrides"]["fixed"] == [
        "P844",
        "P908",
        "P910",
        "P1016",
        "P1017",
        "P1034",
        "P1068",
        "P1076",
        "P1077",
        "P1078",
        "P1079",
        "P1113",
    ]
    assert inventory["attachment_overrides"]["moving"]["A056"] == [
        "P1030",
        "P1028",
        "P1029",
    ]
    assert inventory["attachment_overrides"]["moving"]["A059"] == [
        "P1066",
        "P1072",
        "P1073",
    ]
    assert inventory["attachment_overrides"]["moving"]["A065"] == [
        "P1109",
        "P1107",
        "P1108",
    ]
    assert list(inventory["motion_chains"]) == [
        "Detector",
        "North Crystal",
        "Middle Crystal",
        "South Crystal",
    ]
    assert inventory["motion_chains"]["Detector"] == ["A038"]
    assert inventory["attachment_overrides"]["moving"]["A038"] == ["P803", "P802"]
    assert inventory["motion_chains"]["South Crystal"] == ["A053", "A052", "A051", "A050"]
    assert inventory["attachment_overrides"]["moving"]["A051"] == ["P974"]

    assert list(inventory["compound_motion_chains"]) == [
        "North Polycap",
        "Middle Polycap",
        "South Polycap",
    ]
    z_limits = [joints[0]["limits"] for joints in inventory["compound_motion_chains"].values()]
    assert z_limits == [[-0.004, 0.004]] * 3
    assert all(math.isclose(upper - lower, 0.008) for lower, upper in z_limits)
    assert [
        joints[0]["cad_position"] for joints in inventory["compound_motion_chains"].values()
    ] == [-0.003105455] * 3
    bottom_tower = inventory["compound_motion_chains"]["South Polycap"]
    assert [joint["key"] for joint in bottom_tower] == ["A057:z", "A056:y", "A056:x"]
    assert [joint["moving_role"] for joint in bottom_tower] == ["moving", "y", "x"]
    assert bottom_tower[1]["axis_local"] == [1, 0, 0]
    assert bottom_tower[2]["axis_local"] == [0, 1, 0]
    assert inventory["attachment_overrides"]["moving"]["A057"] == ["P1035"]
    assert inventory["attachment_overrides"]["moving"]["A061"] == ["P1067"]
    assert inventory["attachment_overrides"]["moving"]["A063"] == ["P1114"]
    assert stages["kohzu_za05a_w101_bm"]["component_roles"] == {
        "fixed": [1],
        "moving": [2],
    }
    assert stages["kohzu_ya04a_r102_rrn_bm"]["component_roles"] == {
        "fixed": [2],
        "y": [3],
        "x": [1],
    }
    assert inventory["joint_limit_overrides"]["A043"] == {
        "unit": "degree",
        "limits": [-30, 30],
    }
    assert inventory["joint_limit_overrides"]["A038"] == {
        "unit": "meter",
        "limits": [-0.4, 0.0],
        "home": 0.0,
    }
    assert _reviewed_limits(inventory, "A038", "A038", detector_stage["limits"]) == [
        -0.4,
        0.0,
    ]
    assert _reviewed_home(inventory, "A038", "A038") == 0.0
    assert inventory["joint_limit_overrides"]["A046"] == {
        "unit": "degree",
        "limits": [150, 210],
        "home": 180,
    }


def test_converts_stage_occurrence_transform_to_meters() -> None:
    class Transform:
        def Value(self, row: int, column: int) -> float:
            values = (
                (1.0, 0.0, 0.0, 100.0),
                (0.0, 0.0, -1.0, 200.0),
                (0.0, 1.0, 0.0, 300.0),
            )
            return values[row - 1][column - 1]

    data = _transform_data(Transform())
    assert data["translation_m"] == [0.1, 0.2, 0.3]
    assert data["rotation"] == [[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]]


def test_filters_screws_without_filtering_mounts() -> None:
    assert _is_fastener_name("McMasterCarr__SHCS_M3x.5x8mmSST")
    assert _is_fastener_name("0.25-20 SCREW, HEX SCH CAP")
    assert _is_fastener_name("97163A130_NO THREADS_Tapered Heat-Set Inserts for Plastic")
    assert not _is_fastener_name("Mounting Brackets for Cable and Hose Carrier")


def test_rotates_catalog_axis_into_assembly_frame() -> None:
    rotation = [[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]]
    assert _rotate_vector(rotation, [1.0, 0.0, 0.0]) == [0.0, 1.0, 0.0]


def test_transforms_revolute_pivot_offset_into_assembly_frame() -> None:
    instance = {
        "translation_m": [1.0, 2.0, 3.0],
        "rotation": [[0.0, 0.0, 1.0], [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0]],
    }
    stage = {"pivot_offset_local": [0.0, 0.0, 0.057]}

    assert _joint_origin_m(instance, stage) == [1.057, 2.0, 3.0]


def test_reviewed_angular_limits_are_converted_to_radians() -> None:
    inventory = {
        "joint_limit_overrides": {
            "A043": {"unit": "degree", "limits": [-30, 30]},
        }
    }
    limits = _reviewed_limits(inventory, "A043", "A043", [-3.0, 3.0])
    assert limits == [-math.pi / 6.0, math.pi / 6.0]


def test_reviewed_angular_home_is_converted_to_radians() -> None:
    inventory = {
        "joint_limit_overrides": {
            "A046": {"unit": "degree", "limits": [150, 210], "home": 180},
        }
    }
    assert _reviewed_home(inventory, "A046", "A046") == math.pi


def test_joint_displacement_separates_home_from_imported_cad_position() -> None:
    joint = {"home": 0.0, "cad_position": -0.003105455}

    assert math.isclose(_joint_displacement(joint, 0.0), 0.003105455)
    assert math.isclose(_joint_displacement(joint, -0.004), -0.000894545)
    assert math.isclose(_joint_displacement(joint, 0.004), 0.007105455)
