"""Readable stage labels shared by the motion and collision viewers."""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import yaml

from twin_lab.collision_viewer import SliderJoint, read_joint_metadata


class AssemblySliderJoint(SliderJoint):
    @property
    def label(self) -> str:
        names = {
            "parker_lift_joint": "Spectrometer vertical",
            "parker_cross_joint": "Spectrometer horizontal",
            "analyzer_rotation_joint": "Analyzer rotation",
        }
        for number in range(1, 4):
            for axis in ("translation", "rotation", "tilt"):
                names[f"crystal_{number}_{axis}_joint"] = f"Crystal {number} {axis}"
        return f"{names.get(self.joint_name, self.joint_name)} ({self.unit})"


def read_controls(package: Path) -> list[AssemblySliderJoint]:
    recipe = Path(__file__).resolve().parent / "reviews" / "assembly.yaml"
    record = json.loads((package / "build.json").read_text())
    template = recipe.parent / yaml.safe_load(recipe.read_text())["split_templates"]
    if (
        record["recipe_sha256"] != hashlib.sha256(recipe.read_bytes()).hexdigest()
        or record.get("split_templates_sha256") != hashlib.sha256(template.read_bytes()).hexdigest()
    ):
        raise ValueError("This package is stale. Run build.py --view to load the updated assembly.")
    return [AssemblySliderJoint(**asdict(joint)) for joint in read_joint_metadata(package)]
