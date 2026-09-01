import json
import math
from pathlib import Path

import yaml

from twin_lab.stage_cad_viewer import (
    _auto_amplitude,
    _is_ongoing_playback_end,
    _is_fastener_name,
    _joint_displacement,
    _joint_origin_m,
    _pv_name_labels,
    _reviewed_cad_position,
    _reviewed_home,
    _reviewed_limits,
    _rotate_vector,
    _transform_data,
)


def test_ongoing_playback_end_sentinel_is_case_insensitive() -> None:
    assert _is_ongoing_playback_end("ongoing") is True
    assert _is_ongoing_playback_end("Continuous") is True
    assert _is_ongoing_playback_end("2026-08-26T15:36:40-07:00") is False


def test_pv_name_labels_matches_real_crystal_stack_command_map() -> None:
    labels = _pv_name_labels("config/crystal-stack-command-map.yaml")

    assert labels["A047"] == "POLYCAP:CRY:N:SWI"
    assert labels["A067:x"] == "POLYCAP:PC:N:X"
    assert len(labels) == 19


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

    assert inventory["subassembly"]["ref"] == "A037"
    assert len(instances) == 22
    assert len(references) == len(set(references))
    assert all(instance["catalog"] in stages for instance in instances)

    occurrences = {item["ref"]: item for item in manifest["occurrences"]}
    root_id = occurrences[inventory["subassembly"]["ref"]]["id"]
    jet_root_id = occurrences["A003"]["id"]
    assert all(occurrences[ref]["is_assembly"] for ref in references)
    # The long-jet stack sits outside the focused subassembly but is still driven.
    assert all(
        occurrences[ref]["id"].startswith((f"{root_id}/", f"{jet_root_id}/"))
        for ref in references
    )

    static_geometry = inventory["static_geometry"]
    assert [item["ref"] for item in static_geometry] == [
        "A036",
        "A028",
        "A029",
        "P1355",
        "A023",
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
        "P868",
        "P871",
        "P872",
        "P873",
        "P875",
        "P876",
        "P877",
        "P891",
        "P937",
        "P938",
        "P939",
        "P994",
    ]
    assert visual_styles["attachment_groups"]["polycap_and_holder"]["refs"] == [
        "P1010",
        "P1011",
        "P1054",
        "P1055",
        "P1089",
        "P1090",
    ]
    assert visual_styles["attachment_groups"]["detector_adapter"]["refs"] == [
        "P784",
        "P809",
        "P810",
    ]
    assert visual_styles["attachment_groups"]["detector"]["refs"] == ["P783"]

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

    # OEM travel windows for the long-jet stack, centred on the assembled CAD pose.
    assert stages["kohzu_xa05a_l202_r"]["limits"] == [-0.025, 0.025]
    assert stages["kohzu_xa05a_r202"]["limits"] == [-0.0075, 0.0075]
    assert stages["kohzu_za05a_w101_bm"]["limits"] == [-0.004, 0.004]
    assert stages["kohzu_za05a_w101_bm"]["axis_local"] == [0.0, 0.0, 1.0]

    assert inventory["hidden_occurrences"] == ["P754", "P755", "P756"]
    assert inventory["attachment_overrides"]["fixed"] == [
        "P826",
        "P890",
        "P892",
        "P998",
        "P999",
        "P1016",
        "P1050",
        "P1058",
        "P1059",
        "P1060",
        "P1061",
        "P1095",
        "P027",
        "P003",
        "P020",
        "P022",
        "P024",
        "P026",
        "P041",
        "P043",
        "P045",
    ]
    assert inventory["attachment_overrides"]["moving"]["A058"] == [
        "P1012",
        "P1010",
        "P1011",
    ]
    assert inventory["attachment_overrides"]["moving"]["A061"] == [
        "P1048",
        "P1054",
        "P1055",
    ]
    assert inventory["attachment_overrides"]["moving"]["A067"] == [
        "P1091",
        "P1089",
        "P1090",
    ]
    assert list(inventory["motion_chains"]) == [
        "Detector",
        "North Crystal",
        "Middle Crystal",
        "South Crystal",
        "Long Jet",
    ]
    assert inventory["motion_chains"]["Long Jet"] == ["A006", "A005", "A004"]
    assert inventory["motion_chains"]["Detector"] == ["A040"]
    assert inventory["attachment_overrides"]["moving"]["A040"] == [
        "P784",
        "P783",
        "P809",
        "P810",
    ]
    assert occurrences["A040"]["name"] == "LIB-000032416_oa_14"
    assert occurrences["P806"]["name"] == "430250 Carriage 55mm S14_car"
    assert occurrences["P806"]["parent_id"] == occurrences["A040"]["id"]
    assert occurrences["P784"]["name"] == "DSG-000041969"
    assert occurrences["P783"]["name"] == "EPIX DETECTOR 100P"
    assert inventory["reviewed_connections"][0] == ["P806", "P784", "P783"]
    assert inventory["motion_chains"]["South Crystal"] == ["A055", "A054", "A053", "A052"]
    assert inventory["attachment_overrides"]["moving"]["A053"] == ["P956"]

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
    assert [joint["key"] for joint in bottom_tower] == ["A059:z", "A058:y", "A058:x"]
    assert [joint["moving_role"] for joint in bottom_tower] == ["moving", "y", "x"]
    assert bottom_tower[1]["axis_local"] == [1, 0, 0]
    assert bottom_tower[2]["axis_local"] == [0, 1, 0]
    assert inventory["attachment_overrides"]["moving"]["A059"] == ["P1017"]
    assert inventory["attachment_overrides"]["moving"]["A063"] == ["P1049"]
    assert inventory["attachment_overrides"]["moving"]["A065"] == ["P1096"]
    assert stages["kohzu_za05a_w101_bm"]["component_roles"] == {
        "fixed": [1],
        "moving": [2],
    }
    assert stages["kohzu_ya04a_r102_rrn_bm"]["component_roles"] == {
        "fixed": [2],
        "y": [3],
        "x": [1],
    }
    assert inventory["joint_limit_overrides"]["A045"] == {
        "unit": "degree",
        "limits": [-30, 30],
    }
    assert inventory["joint_limit_overrides"]["A040"] == {
        "unit": "meter",
        "limits": [-0.4, 0.0],
        "home": 0.0,
    }
    assert _reviewed_limits(inventory, "A040", "A040", detector_stage["limits"]) == [
        -0.4,
        0.0,
    ]
    assert _reviewed_home(inventory, "A040", "A040") == 0.0
    # The jet lift is assembled at the bottom of its stroke, so its travel runs one way
    # from the CAD pose and home sits at that same lower endpoint.
    assert _reviewed_limits(inventory, "A004", "A004", stages["kohzu_za05a_w101_bm"]["limits"]) == [
        0.0,
        0.008,
    ]
    assert _reviewed_home(inventory, "A004", "A004") == 0.0
    assert _reviewed_cad_position(inventory, "A004", "A004") == 0.0
    assert _reviewed_cad_position(inventory, "A040", "A040") == 0.0
    assert inventory["joint_limit_overrides"]["A048"] == {
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


def test_auto_amplitude_stays_inside_the_shorter_side_of_reviewed_limits() -> None:
    off_center = {"limits": [-0.2, 0.2], "home": 0.15}

    assert math.isclose(_auto_amplitude(off_center, 1.0), 0.05)
    assert math.isclose(_auto_amplitude(off_center, 0.25), 0.0125)
    assert _auto_amplitude(off_center, 0.0) == 0.0

    for fraction in (0.0, 0.25, 0.6, 1.0):
        amplitude = _auto_amplitude(off_center, fraction)
        assert off_center["limits"][0] <= off_center["home"] - amplitude
        assert off_center["home"] + amplitude <= off_center["limits"][1]


def test_auto_amplitude_is_zero_when_home_sits_on_a_limit() -> None:
    assert _auto_amplitude({"limits": [0.0, 0.4], "home": 0.0}, 1.0) == 0.0
    assert _auto_amplitude({"limits": [0.0, 0.4], "home": -0.01}, 1.0) == 0.0
