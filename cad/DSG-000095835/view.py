"""Offline motion viewer with stage controls in millimetres and degrees."""

from __future__ import annotations

import math
import time
from pathlib import Path

import numpy as np
from controls import read_controls
from pydrake.geometry import Meshcat

from twin_lab.collision_viewer import isometric_camera
from twin_lab.meshcat_ui import announce_viewer, patch_meshcat_page, viewer_params
from twin_lab.scene import load_scene


def view(package: Path, *, once: bool = False) -> None:
    patch_meshcat_page()
    meshcat = Meshcat(viewer_params())
    scene = load_scene(package / "DSG-000095835.sdf", meshcat=meshcat)
    context = scene.create_context()
    joints = read_controls(package)
    for joint in joints:
        low, high, home = joint.slider_bounds()
        meshcat.AddSlider(joint.label, low, high, 0.05, home)
    meshcat.AddSlider("Animation", 0.0, 1.0, 1.0, 0.0)
    meshcat.AddSlider("Auto motion range (% of travel)", 0.0, 100.0, 1.0, 10.0)
    meshcat.AddSlider("Auto motion period (s)", 2.0, 60.0, 1.0, 20.0)
    meshcat.AddButton("Reset to home")
    meshcat.AddButton("Stop viewer", "Escape")
    # Fit actual illustration vertices; geometry frames alone do not give CAD extents.
    lower, upper = np.full(3, np.inf), np.full(3, -np.inf)
    for mesh in (package / "meshes").glob("*.obj"):
        with mesh.open() as stream:
            points = np.array(
                [list(map(float, line.split()[1:4])) for line in stream if line.startswith("v ")]
            )
        if len(points):
            lower, upper = np.minimum(lower, points.min(0)), np.maximum(upper, points.max(0))
    eye, center = isometric_camera(lower, upper)
    meshcat.SetCameraPose(eye, center)
    scene.diagram.ForcedPublish(context)
    announce_viewer("DSG-000095835 offline motion", meshcat, open_browser=not once)
    print(f"{len(joints)} stage controls. CAD pose is zero; reset returns every axis to zero.")
    print("Motion preview only. Use build.py --collision convex --view for clearance review.")
    reset_clicks = 0
    started = time.monotonic()
    last_push = 0.0
    try:
        while meshcat.GetButtonClicks("Stop viewer") == 0:
            now = time.monotonic()
            if meshcat.GetButtonClicks("Reset to home") != reset_clicks:
                reset_clicks = meshcat.GetButtonClicks("Reset to home")
                meshcat.SetSliderValue("Animation", 0.0)
                for joint in joints:
                    meshcat.SetSliderValue(joint.label, joint.reviewed_home * joint.scale)
            automatic = meshcat.GetSliderValue("Animation") > 0.5
            positions = {}
            for index, joint in enumerate(joints):
                value = joint.to_sdf(meshcat.GetSliderValue(joint.label))
                if automatic:
                    fraction = meshcat.GetSliderValue("Auto motion range (% of travel)") / 100
                    period = meshcat.GetSliderValue("Auto motion period (s)")
                    amplitude = min(-joint.sdf_lower, joint.sdf_upper) * fraction
                    value = amplitude * math.sin(2 * math.pi * (now - started) / period + index)
                    if now - last_push >= 0.2:
                        meshcat.SetSliderValue(joint.label, value * joint.scale)
                positions[f"DSG-000095835::{joint.joint_name}"] = value
            if now - last_push >= 0.2:
                last_push = now
            scene.set_joint_positions(context, positions)
            scene.diagram.ForcedPublish(context)
            meshcat.Flush()
            if once:
                break
            time.sleep(1 / 30)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--package",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "exports/DSG-000095835",
    )
    args = parser.parse_args()
    view(args.package, once=args.once)
