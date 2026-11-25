"""Offline motion viewer with stage controls in millimetres and degrees."""

from __future__ import annotations

import math
import os
import tempfile
import time
from pathlib import Path

import numpy as np
from controls import read_controls, read_followers, with_followers
from pydrake.geometry import Meshcat

from twin_lab.collision_viewer import isometric_camera
from twin_lab.meshcat_ui import announce_viewer, patch_meshcat_page, viewer_params
from twin_lab.scene import load_scene


def view(package: Path, *, once: bool = False, spectroscopy: bool = False) -> None:
    if not spectroscopy:
        patch_meshcat_page()
        _view(package, once=once, spectroscopy=False)
        return

    from spectroscopy_view import detector_panel

    previous = os.environ.get("DRAKE_RESOURCE_ROOT")
    with tempfile.TemporaryDirectory(prefix="twinlab-95835-") as directory:
        patch_meshcat_page(
            extra_html=detector_panel(read_controls(package)), resource_root=Path(directory),
        )
        try:
            _view(package, once=once, spectroscopy=True)
        finally:
            if previous is None:
                os.environ.pop("DRAKE_RESOURCE_ROOT", None)
            else:
                os.environ["DRAKE_RESOURCE_ROOT"] = previous


def _view(package: Path, *, once: bool, spectroscopy: bool) -> None:
    meshcat = Meshcat(viewer_params())
    scene = load_scene(package / "DSG-000095835.sdf", meshcat=meshcat)
    context = scene.create_context()
    joints = read_controls(package)
    followers = read_followers()
    if spectroscopy:
        from spectroscopy import Spectrometer
        from spectroscopy_view import SpectroscopyPreview

        preview = SpectroscopyPreview(
            meshcat, Spectrometer(scene, context), scene, joints, followers,
        )
    else:
        preview = None
    bounds = [
        joint.spectroscopy_bounds() if spectroscopy else joint.slider_bounds() for joint in joints
    ]
    for joint, (low, high, home) in zip(joints, bounds, strict=True):
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
    if preview is not None:
        label = "DSG-000095835 offline ePix100 spectroscopy"
    else:
        label = "DSG-000095835 offline motion"
    announce_viewer(label, meshcat, open_browser=not once)
    print(f"{len(joints)} stage controls. CAD pose is zero; reset returns every axis to zero.")
    print("Collision checking is off. Use build.py --collision convex --view for clearance review.")
    reset_clicks = 0
    started = time.monotonic()
    last_push = 0.0
    try:
        while meshcat.GetButtonClicks("Stop viewer") == 0:
            now = time.monotonic()
            if meshcat.GetButtonClicks("Reset to home") != reset_clicks:
                reset_clicks = meshcat.GetButtonClicks("Reset to home")
                meshcat.SetSliderValue("Animation", 0.0)
                for joint, (_, _, home) in zip(joints, bounds, strict=True):
                    meshcat.SetSliderValue(joint.label, home)
            automatic = meshcat.GetSliderValue("Animation") > 0.5
            positions = {}
            for index, (joint, (low, high, _)) in enumerate(zip(joints, bounds, strict=True)):
                slider = meshcat.GetSliderValue(joint.label)
                if automatic:
                    fraction = meshcat.GetSliderValue("Auto motion range (% of travel)") / 100
                    period = meshcat.GetSliderValue("Auto motion period (s)")
                    amplitude = min(-low, high) * fraction
                    slider = amplitude * math.sin(2 * math.pi * (now - started) / period + index)
                    if now - last_push >= 0.2:
                        meshcat.SetSliderValue(joint.label, slider)
                value = joint.to_sdf(min(max(slider, low), high))
                # The degree conversion may round an end stop a few ulps outside the SDF.
                value = min(max(value, joint.sdf_lower), joint.sdf_upper)
                positions[f"DSG-000095835::{joint.joint_name}"] = value
            if now - last_push >= 0.2:
                last_push = now
            scene.set_joint_positions(
                context, with_followers(positions, followers, prefix="DSG-000095835::")
            )
            if preview is not None:
                preview.update(context, positions, automatic=automatic)
            scene.diagram.ForcedPublish(context)
            meshcat.Flush()
            if once:
                break
            time.sleep(1 / 30)
    except KeyboardInterrupt:
        pass
    finally:
        if preview is not None:
            preview.close()


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
