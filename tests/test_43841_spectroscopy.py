"""Verify the flat analyzer trace and the published PCXS starting-pose workflow."""

import json
import math
import sys
from threading import Event
from unittest.mock import Mock

import numpy as np
import pytest

from twin_lab import launcher
from twin_lab.beam import Plane, intersect_plane
from twin_lab.paths import CACHE_ROOT
from twin_lab.spectroscopy import Detector, bragg_angle
from twin_lab.spectroscopy_43841 import (
    DEFAULT_HALF_WIDTH_DEG,
    LINES,
    CrystalFace,
    chain_pose,
    disk_offsets,
    load_crystal_face,
    load_spectrometer,
    trace_flat,
)
from twin_lab.spectroscopy_align import AlignmentRequest, find_alignment, find_starting_poses
from twin_lab.spectroscopy_plan import compare_reflections


def test_launcher_routes_spectroscopy_without_enabling_collision(monkeypatch):
    execute = Mock()
    monkeypatch.setattr(launcher.os, "execv", execute)
    monkeypatch.setattr(sys, "argv", ["slac-run", "43841", "--spectroscopy", "--once"])
    launcher.main()
    execute.assert_called_once_with(sys.executable, [
        sys.executable, "-m", "twin_lab.spectroscopy_43841", launcher.INVENTORY_43841, "--once",
    ])


def test_parallel_rays_need_the_front_of_the_flat_crystal_and_active_sensor():
    x, y, z = np.eye(3)
    source = Plane(np.zeros(3), z, 0.010)
    long = (x + z) / math.sqrt(2)
    crystal = CrystalFace(z * 0.1, np.array([long, -y, (x - z) / math.sqrt(2)]), (0.020, 0.006))
    sensor = Detector(x * 0.1 + z * 0.1, z, y, -x)
    offsets = disk_offsets(source.radius_m)
    theta = math.pi / 4
    on_chip = trace_flat(source, crystal, sensor, offsets, theta, 1e-4)
    assert 32 < on_chip.accepted < len(offsets)  # The oblique footprint clips at the crystal.
    assert len(on_chip.weights) == on_chip.accepted
    np.testing.assert_allclose(on_chip.uv_m.mean(axis=0), [0, 0], atol=1e-12)
    np.testing.assert_allclose(on_chip.preview_start_m[:, 2], 0)
    shifted = Detector(sensor.center_m + y * 0.040, z, y, -x)
    off_chip = trace_flat(source, crystal, shifted, offsets, theta, 1e-4)
    assert off_chip.accepted == on_chip.accepted
    assert not len(off_chip.weights)
    wrong_energy = trace_flat(source, crystal, sensor, offsets, theta + 0.01, 1e-4, aim=True)
    assert wrong_energy.accepted == 0
    assert wrong_energy.projected_uv_m is not None  # Guidance is not a detector hit.
    back = CrystalFace(crystal.center_m, crystal.axes * [[1], [-1], [-1]], crystal.half_size_m)
    assert trace_flat(source, back, sensor, offsets, theta, 1e-4).accepted == 0


def test_plate_face_uses_the_rectangular_solid_not_the_higher_holder_tabs(tmp_path):
    manifest = tmp_path / "manifest.json"
    transform = np.eye(4)
    transform[:3, 3] = [100, 200, 300]
    manifest.write_text(json.dumps({"occurrences": [{
        "id": "holder", "ref": "P001", "transform_to_parent": transform.tolist(),
    }]}))
    mesh = tmp_path / "holder.obj"
    tabs = "v .08 .22 .33\nv .12 .22 .33\nv .12 .23 .33\n"
    plate = "v .065 .185 .3147\nv .135 .185 .3147\nv .135 .215 .3147\nv .065 .215 .3147\n"
    mesh.write_text(tabs + plate + "o P001\nf 1 2 3\nf 4 5 6\nf 4 6 7\n")
    face = load_crystal_face(mesh, "P001", manifest)
    np.testing.assert_allclose(face.center_m, [.100, .200, .3147])
    assert face.contains(face.center_m + np.array([[.034, 0, 0], [0, .016, 0]])).tolist() == [
        True, False,
    ]
    mesh.write_text(tabs + "o P001\nf 1 2 3\n")
    with pytest.raises(ValueError, match="crystal front face not found"):
        load_crystal_face(mesh, "P001", manifest)


def test_pt_starting_pose_recovers_all_three_cad_paths_and_scans_the_band():
    scene = CACHE_ROOT / "stage-cad" / "DSG-000040389.43841-stage-stack" / "scene.yaml"
    if not scene.exists():
        pytest.skip("requires the local 43841 CAD cache from --spectroscopy --prepare-only")
    model = load_spectrometer(scene)
    rig = model.rig()
    chains = [model.detector_chain]
    for path in model.paths:
        chains.extend((path.source_chain, path.crystal_chain))
    home = {joint["key"]: joint["home"] for chain in chains for joint in chain}
    original = home.copy()
    energy, spacing, width = LINES[0][1], model.reflections[0].spacing_a, DEFAULT_HALF_WIDTH_DEG
    theta = bragg_angle(energy, spacing, 1)
    assert theta is not None
    assert math.degrees(theta) == pytest.approx(23.05, abs=0.01)
    request = AlignmentRequest(energy, spacing, 1, width)
    poses = find_starting_poses(home, model, rig, home, request, Event())
    assert home == original
    assert poses and model.reflections[poses[0].reflection].label == "Graphite(004)"
    best = poses[0].alignment
    assert best.before.hits == (0, 0, 0)
    assert best.after.signal_rank() == (3, 3)
    proposed = {}
    for axis, value in zip(rig.axes, best.target, strict=True):
        assert axis.lower - 1e-9 <= value <= axis.upper + 1e-9
        proposed[axis.key] = axis.from_slider(value)
    _, _, traces = model.trace(proposed, energy, spacing, 1, width)
    assert tuple(len(trace.weights) for trace in traces) == best.after.hits
    for path, trace in zip(model.paths, traces, strict=True):
        source = path.source.transformed(chain_pose(path.source_chain, proposed))
        plate = path.crystal.moved(chain_pose(path.crystal_chain, proposed))
        axis_ray = intersect_plane(source.origin_m, source.normal, Plane(
            plate.center_m, plate.normal, 0.0,
        ))
        assert axis_ray is not None
        assert np.linalg.norm(axis_ray[1] - plate.center_m) < .001, path.name
        np.testing.assert_allclose((trace.bounce_m - plate.center_m) @ plate.normal, 0, atol=1e-10)
        assert np.all(plate.contains(trace.bounce_m))
    energies, rows = compare_reflections(model, proposed, energy, 5, 5, width)
    assert (energies[0], energies[-1]) == pytest.approx((9437.3, 9447.3))
    assert len(rows[0].points) == len(energies) == 21
    assert all(len(sample) == 3 for sample in rows[0].points)
    assert rows[0].reflection == poses[0].reflection
    assert rows[0].geometry_rank()[0] > 0

    before_refine = proposed.copy()
    target = (4.0, 4.0)
    refined = find_alignment(
        proposed.copy(), model, rig, proposed, AlignmentRequest(energy, spacing, 1, width, target),
        Event(),
    )
    assert proposed == before_refine
    assert refined is not None
    assert refined.before.centroid_mm is not None and refined.after.centroid_mm is not None
    assert np.linalg.norm(refined.after.centroid_mm - target) < 1
    assert all(
        after >= before
        for before, after in zip(refined.before.hits, refined.after.hits, strict=True)
    )
