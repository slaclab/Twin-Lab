"""Check the Bragg math and its connection to the moving 95835 sensor."""

import json
import math
import xml.etree.ElementTree as ET
from importlib import import_module
from pathlib import Path
from threading import Event
from unittest.mock import Mock

import numpy as np
import pytest

from twin_lab.scene import load_scene

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def optics(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "cad" / "DSG-000095835"))
    return import_module("spectroscopy")


def test_second_order_uses_the_same_bragg_angle_as_halved_spacing(optics):
    energy = 7000
    expected = math.asin((12398.419843 / energy) / 2)
    assert optics.bragg_angle(energy, 2, 2) == pytest.approx(expected)
    assert optics.bragg_angle(energy, 1, 1) == pytest.approx(expected)
    assert optics.bragg_angle(energy, 1, 2) is None


def test_concave_surface_focuses_rays_and_sensor_can_clip_them(optics):
    # Source and focus lie on the cylinder axis, equally far apart from the midplane.
    # Every sample on the central arc has the same glancing angle.
    source = np.array([0.0, 0.0, -0.1])
    aperture = optics.cylinder_aperture(
        np.zeros(3), np.eye(3), 0.25, (-0.2, 0.2, -1e-9, 1e-9), samples=(41, 1),
    )
    detector = optics.Detector(
        np.array([0.0, 0.0, 0.1]), np.eye(3)[0], np.eye(3)[1], -np.eye(3)[2],
    )
    angle = math.atan2(0.25, 0.1)
    trace = optics.trace_crystal(source, aperture, np.eye(4), detector, angle, 1e-5)
    assert trace.accepted == len(trace.weights) == 41
    image, center, rms = optics.detector_image([trace])
    assert image.sum() == pytest.approx(trace.weights.sum(), rel=1e-12, abs=1e-22)
    np.testing.assert_allclose(center, [0, 0], atol=1e-9)
    np.testing.assert_allclose(rms, [0, 0], atol=1e-9)

    pose = np.eye(4)
    pose[0, 3] = 0.030
    missed = optics.trace_crystal(source, aperture, np.eye(4), detector.moved(pose), angle, 1e-5)
    assert missed.accepted == 41
    assert len(missed.weights) == 0
    image, center, rms = optics.detector_image([missed])
    assert not image.any()
    assert center is rms is None


@pytest.fixture
def cad_spectrometer(optics):
    from twin_lab.paths import EXPORT_ROOT

    build = import_module("build")
    package = next(
        (EXPORT_ROOT / name for name in ("DSG-000095835-spectroscopy", "DSG-000095835")
         if (EXPORT_ROOT / name / "DSG-000095835.sdf").exists()),
        EXPORT_ROOT / "DSG-000095835",
    )
    sdf = package / "DSG-000095835.sdf"
    if not sdf.exists() or not (build.CACHE / "stats.json").exists():
        pytest.skip("requires the local 95835 STEP cache and motion or collision package")
    scene = load_scene(sdf)
    context = scene.create_context()
    return scene, context, optics.Spectrometer(scene, context), package


def test_fe_demo_detector_and_crystal_stage_changes(optics, cad_spectrometer):
    scene, context, spectrometer, _ = cad_spectrometer

    def trace():
        return spectrometer.trace(context, 7058.2, optics.REFLECTIONS[0][1], 1, 0.05)[2]

    at_home = trace()
    _, center, _ = optics.detector_image(at_home)
    assert center is not None
    assert len(at_home[0].weights) > 0 and len(at_home[1].weights) > 0

    scene.set_joint_positions(context, {"DSG-000095835::epix100_x_joint": -0.004})
    shifted = trace()
    _, shifted_center, _ = optics.detector_image(shifted)
    assert shifted_center is not None
    np.testing.assert_allclose(shifted_center - center, [-4, 0], atol=1e-7)
    assert [t.accepted for t in shifted] == [t.accepted for t in at_home]

    scene.set_joint_positions(context, {"DSG-000095835::crystal_1_translation_joint": 0.01})
    moved = trace()
    assert moved[0].incidence_deg != shifted[0].incidence_deg
    np.testing.assert_allclose(moved[1].uv_m, shifted[1].uv_m)

    context = scene.create_context()
    scene.set_joint_positions(context, {
        "DSG-000095835::parker_lift_joint": -0.01910,
        "DSG-000095835::analyzer_rotation_joint": math.radians(0.45),
        "DSG-000095835::epix100_x_joint": 0.00195,
        "DSG-000095835::epix100_y_joint": -0.00830,
        "DSG-000095835::epix100_z_joint": -0.00650,
    })
    focused = trace()
    _, center, rms = optics.detector_image(focused)
    assert center is not None and rms is not None
    assert np.linalg.norm(center) < 0.2
    assert np.all(rms < 0.35)
    assert len(focused[0].weights) > 0 and len(focused[1].weights) > 0


def test_spectroscopy_package_excludes_scattering_detector(cad_spectrometer):
    scene, _, _, package = cad_spectrometer
    if package.name != "DSG-000095835-spectroscopy":
        pytest.skip("requires a fresh 95835 export from --spectroscopy")
    controls = import_module("controls")
    joints = {joint.joint_name: joint for joint in controls.read_controls(package)}
    for name in ("detector_x", "detector_y", "detector_z", "detector_y_wedge"):
        assert not scene.plant.HasBodyNamed(name)
        assert f"{name}_joint" not in joints
    assert scene.plant.HasBodyNamed("epix100_tilt")
    assembly = ROOT / "cad" / "DSG-000095835"
    entries = json.loads((assembly / "manifest.json").read_text())["occurrences"]
    scattering, = (entry["id"] for entry in entries if entry["name"].startswith("LCL5005-008450"))
    removed = {entry["ref"] for entry in entries if entry["id"].startswith(scattering + "/")}
    sdf = ET.parse(package / "DSG-000095835.sdf")
    mesh_tokens = {
        token for uri in sdf.findall(".//uri") if uri.text
        for token in Path(uri.text).stem.split("_")
    }
    assert mesh_tokens
    assert mesh_tokens.isdisjoint(removed)
    assert joints["epix100_x_joint"].spectroscopy_bounds()[0] == -6.5
    y = joints["epix100_y_joint"]
    assert y.spectroscopy_bounds() == y.slider_bounds()
    assert joints["epix100_z_joint"].spectroscopy_bounds() == (-6.5, 6.5, 0)


@pytest.mark.parametrize(
    ("line", "reflection", "target", "max_error"),
    [(0, 0, (0.0, 0.0), 0.5), (0, 0, (5.0, 5.0), 0.5), (4, 1, (5.0, 5.0), 2.5)],
    ids=["Fe-center", "Fe-offset", "Mn-offset"],
)
def test_auto_align_moves_each_crystal_in_a_private_context(
    optics, cad_spectrometer, line, reflection, target, max_error,
):
    scene, context, spectrometer, package = cad_spectrometer
    align = import_module("spectroscopy_align")
    controls = import_module("controls")
    if package.name != "DSG-000095835-spectroscopy":
        pytest.skip("requires a fresh 95835 export from --spectroscopy")
    joints = controls.read_controls(package)
    positions = {align.PREFIX + joint.joint_name: 0.0 for joint in joints}
    followers = controls.read_followers()
    energy, spacing = optics.LINES[line][1], optics.REFLECTIONS[reflection][1]
    request = align.AlignmentRequest(energy, spacing, 1, 0.05, target)
    plant_context = scene.plant.GetMyContextFromRoot(context)
    original_positions = scene.plant.GetPositions(plant_context).copy()
    result = align.find_alignment(
        scene, context.Clone(), spectrometer, joints, followers, positions, request, Event(),
    )
    np.testing.assert_array_equal(scene.plant.GetPositions(plant_context), original_positions)
    assert result is not None
    assert result.after.centroid_mm is not None and result.after.rms_mm is not None
    assert result.detector_target_mm == target
    assert np.linalg.norm(result.after.centroid_mm - target) < max_error
    assert np.all(result.after.rms_mm < 4)
    assert len(result.after.hits) == 4
    assert all(
        hits >= max(32, before, 0.8 * accepted)
        for hits, before, accepted in zip(
            result.after.hits, result.before.hits, result.after.accepted, strict=True,
        )
    )
    _, _, traces = spectrometer.trace(context, energy, spacing, 1, 0.05)
    assert tuple(len(trace.weights) for trace in traces) == result.before.hits
    assert not np.array_equal(result.before.image, result.after.image)
    by_name = {joint.joint_name: joint for joint in joints}
    for name, value in zip(align.AXES, result.target, strict=True):
        joint = by_name[name]
        first, last, _ = joint.spectroscopy_bounds()
        assert first <= value <= last
        assert joint.sdf_lower <= joint.to_sdf(value) <= joint.sdf_upper
        assert value / align.STAGE_STEP == pytest.approx(round(value / align.STAGE_STEP))
    proposed = dict(zip(align.AXES, result.target, strict=True))
    assert all(proposed[f"crystal_{i}_tilt_joint"] != 0 for i in range(1, 5))
    applied = {align.PREFIX + name: by_name[name].to_sdf(v) for name, v in proposed.items()}
    scene.set_joint_positions(context, controls.with_followers(applied, followers, align.PREFIX))
    _, _, traces = spectrometer.trace(context, energy, spacing, 1, 0.05)
    image, center, rms = optics.detector_image(traces)
    np.testing.assert_array_equal(image, result.after.image)
    np.testing.assert_allclose(center, result.after.centroid_mm)
    np.testing.assert_allclose(rms, result.after.rms_mm)


def test_search_skips_impossible_bragg_and_rejects_an_off_chip_target(optics):
    align = import_module("spectroscopy_align")
    energy = optics.LINES[9][1]  # Ti Kβ1,3 with Ge(620) has no real Bragg angle.
    spacing = optics.REFLECTIONS[0][1]
    forbidden = align.AlignmentRequest(energy, spacing, 1, 0.05)
    # Neither case should touch a scene or evaluate any ray traces.
    scene, context, spectrometer = Mock(), Mock(), Mock()
    result = align.find_alignment(scene, context, spectrometer, [], {}, {}, forbidden, Event())
    assert result is None
    off_chip = align.AlignmentRequest(7058.2, spacing, 1, 0.05, (20.0, 0.0))
    with pytest.raises(ValueError, match="inside the active ePix100"):
        align.find_alignment(scene, context, spectrometer, [], {}, {}, off_chip, Event())
    scene.set_joint_positions.assert_not_called()
    spectrometer.trace.assert_not_called()
