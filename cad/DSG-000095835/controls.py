"""Readable stage labels shared by the motion and collision viewers."""

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path

import yaml

from twin_lab.collision_viewer import SliderJoint, read_joint_metadata

RECIPE = Path(__file__).resolve().parent / "reviews" / "assembly.yaml"


class AssemblySliderJoint(SliderJoint):
    @property
    def label(self) -> str:
        names = {
            "parker_lift_joint": "Spectrometer vertical",
            "parker_cross_joint": "Spectrometer horizontal",
            "analyzer_rotation_joint": "Analyzer rotation",
            "lj_x_joint": "LJ x",
            "lj_y_joint": "LJ y",
            "lj_z_joint": "LJ z",
            "bottom_slit_x_joint": "Bottom slit x",
            "bottom_slit_y_joint": "Bottom slit y",
            "top_slit_x_joint": "Top slit x",
            "top_slit_y_joint": "Top slit y",
            "detector_x_joint": "ePix10k x",
            "detector_y_joint": "ePix10k y",
            "detector_z_joint": "ePix10k z",
            "epix100_x_joint": "ePix100 x",
            "epix100_y_joint": "ePix100 y",
            "epix100_z_joint": "ePix100 z",
            "epix100_tilt_joint": "ePix100 tilt",
        }
        for number in range(1, 5):
            for axis in ("translation", "rotation", "tilt"):
                names[f"crystal_{number}_{axis}_joint"] = f"Crystal {number} {axis}"
        return f"{names.get(self.joint_name, self.joint_name)} ({self.unit})"


def follower_position(rule: Mapping, leader: float) -> float:
    """Position of a slaved joint for its leader's position, both in SI units.

    ``ratio`` is a linear coupling, such as a 1/4 wedge. ``scissor`` is a lab-jack arm of
    length ``arm_m`` whose pivots are ``rise_m`` apart vertically at the CAD pose, and whose
    leader lifts one pivot by its position: ``angle`` is the arm's rotation and ``slide`` the
    change in the pivots' horizontal spacing, both zero at the CAD pose.
    """
    if "ratio" in rule:
        return float(rule["ratio"]) * leader
    scissor = rule["scissor"]
    arm, rise = float(scissor["arm_m"]), float(scissor["rise_m"])
    sine = min(max((rise + leader) / arm, -1.0), 1.0)
    if scissor["output"] == "angle":
        return math.asin(sine) - math.asin(rise / arm)
    if scissor["output"] == "slide":
        return arm * (math.sqrt(1.0 - sine**2) - math.sqrt(1.0 - (rise / arm) ** 2))
    raise ValueError(f"Unknown scissor output {scissor['output']!r}")


def read_followers() -> dict[str, tuple[str, dict]]:
    """Map each slaved joint to the joint it follows and its coupling rule, from the recipe."""
    recipe = yaml.safe_load(RECIPE.read_text())
    return {
        joint["name"]: (
            joint["follows"]["joint"],
            {key: value for key, value in joint["follows"].items() if key != "joint"},
        )
        for joint in recipe["joints"]
        if "follows" in joint
    }


def with_followers(
    positions: Mapping[str, float], followers: Mapping[str, tuple[str, Mapping]], prefix: str = ""
) -> dict[str, float]:
    """Return positions with every follower set from its leader, overriding stale values."""
    result = dict(positions)
    for follower, (leader, rule) in followers.items():
        if prefix + leader in result:
            result[prefix + follower] = follower_position(rule, float(result[prefix + leader]))
    return result


def read_controls(package: Path) -> list[AssemblySliderJoint]:
    template = RECIPE.parent / yaml.safe_load(RECIPE.read_text())["split_templates"]
    record = json.loads((package / "build.json").read_text())
    if (
        record["recipe_sha256"] != hashlib.sha256(RECIPE.read_bytes()).hexdigest()
        or record.get("split_templates_sha256") != hashlib.sha256(template.read_bytes()).hexdigest()
    ):
        raise ValueError("This package is stale. Run build.py --view to load the updated assembly.")
    followers = read_followers()
    # Followers have no slider; the viewers derive them from their leader.
    return [
        AssemblySliderJoint(**asdict(joint))
        for joint in read_joint_metadata(package)
        if joint.joint_name not in followers
    ]
