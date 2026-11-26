"""Verify the flat analyzer trace and the published PCXS starting-pose workflow."""

import json
import math
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock

import numpy as np
import pytest

from twin_lab import launcher
from twin_lab.beam import Plane, intersect_plane
from twin_lab.collision import Clearance, ClearanceReport
from twin_lab.collision_viewer import SliderJoint
from twin_lab.paths import CACHE_ROOT
from twin_lab.spectroscopy import Detector, bragg_angle, detector_image
from twin_lab.spectroscopy_43841 import (
    DEFAULT_HALF_WIDTH_DEG,
    DETECTOR_TARGET_AXES,
    LINES,
    CrystalFace,
    chain_pose,
    collision_positions,
    disk_offsets,
    load_crystal_face,
    load_spectrometer,
    trace_flat,
)
from twin_lab.spectroscopy_align import (
    AlignmentAxis,
    AlignmentImage,
    AlignmentRequest,
    AlignmentResult,
    AlignmentRig,
    ClearanceSearch,
    StartingPose,
    find_alignment,
    find_starting_poses,
)
from twin_lab.spectroscopy_plan import compare_reflections
from twin_lab.spectroscopy_view import (
    ALIGN,
    APPLY,
    CANDIDATE,
    REFLECTION,
    TARGET_U,
    TARGET_V,
    TRY_REFLECTIONS,
    AlignmentPreview,
    AlignmentStatus,
    InterferencePreview,
    InterferenceStatus,
    SpectroscopyPreview,
    TargetMoveStatus,
)


def test_launcher_routes_to_flat_spectroscopy_viewer(monkeypatch):
    execute = Mock()
    monkeypatch.setattr(launcher.os, "execv", execute)
    monkeypatch.setattr(sys, "argv", ["slac-run", "43841", "--spectroscopy", "--once"])
    launcher.main()
    execute.assert_called_once_with(sys.executable, [
        sys.executable, "-m", "twin_lab.spectroscopy_43841", launcher.INVENTORY_43841, "--once",
    ])


def test_collision_pose_preserves_sdf_offsets_and_hidden_slit_home():
    joints = {
        "A231:z": SliderJoint(
            "north_polycap_a231_z", "North Polycap", "A231", "prismatic",
            -0.000894545, 0.007105455, -0.003105455, 0,
        ),
        "A024": SliderJoint(
            "lj_detector_1_a024_motion", "LJ Detector 1", "A024", "prismatic",
            -0.004, 0.004, 0, 0.001,
        ),
    }
    hidden = frozenset({"A024"})
    assert collision_positions({"A231:z": -0.001}, joints, hidden) == pytest.approx({
        "north_polycap_a231_z": 0.002105455, "lj_detector_1_a024_motion": 0.001,
    })
    with pytest.raises(ValueError, match="missing reviewed joints"):
        collision_positions({"A231": -0.001}, joints, hidden)


def _interfering_report():
    return ClearanceReport(
        (Clearance("model::base::P2239", "model::north_polycap::P2783", -0.004),),
        warn_m=0, part_labels={"P2783": "REF-000221284"},
    )


def _finish_check(preview, *, proposed=False):
    slot = preview.proposed if proposed else preview.live
    assert slot.in_flight is not None
    slot.in_flight[1].result(timeout=3)


def test_live_check_never_publishes_a_result_for_an_old_slider_pose():
    controls = Mock()
    release = Event()

    def check(pose):
        if pose["A231:z"] == 0:
            assert release.wait(timeout=3)
            return ClearanceReport((), warn_m=0)
        return _interfering_report()

    preview = InterferencePreview(controls, "/test", check, ThreadPoolExecutor(max_workers=1))
    try:
        preview.update({"A231:z": 0})
        moved = {"A231:z": -0.001}
        assert preview.update(moved) == InterferenceStatus.PENDING
        release.set()
        _finish_check(preview)
        assert preview.update(moved) == InterferenceStatus.PENDING
        _finish_check(preview)
        assert preview.update(moved) == InterferenceStatus.INTERFERENCE
        frames = [call.args[2] for call in controls.SetProperty.call_args_list]
        assert all(frame[0] != InterferenceStatus.CLEAR for frame in frames)
        assert "north_polycap/REF-000221284: -4.00 mm" in bytes(map(int, frames[-1][1:])).decode()
    finally:
        release.set()
        preview.close()


@pytest.mark.parametrize("unavailable", [False, True])
def test_apply_requires_clear_selected_endpoint_and_fresh_full_pose(monkeypatch, unavailable):
    controls = Mock()
    clicks, sliders = {ALIGN: 0, APPLY: 0}, {CANDIDATE: 0, TRY_REFLECTIONS: 1}
    controls.GetButtonClicks.side_effect = lambda name: clicks.get(name, 0)
    controls.GetSliderValue.side_effect = sliders.__getitem__
    axis = AlignmentAxis("A205", "Detector u", -12.5, 12.5, lambda x: 1000 * x, lambda x: x / 1000)
    rig = AlignmentRig((axis,), (), dict.update, dict.copy)
    frame = AlignmentImage(np.zeros((1, 1)), None, None, (812, 812, 812), (812, 812, 812))
    proposals = [
        StartingPose(i, AlignmentResult((0,), (move,), (0, 0), frame, frame))
        for i, move in enumerate((2, 1))
    ]
    monkeypatch.setattr("twin_lab.spectroscopy_view.find_starting_poses", lambda *a, **k: proposals)
    release = Event()

    def check(pose):
        assert release.wait(timeout=3)
        if unavailable:
            return None
        return _interfering_report() if pose["A205"] == 0.002 else ClearanceReport((), warn_m=0)

    interference = InterferencePreview(
        controls, "/test", check, ThreadPoolExecutor(max_workers=1),
    )
    preview = AlignmentPreview(controls, Mock(), rig, "/test", interference)
    pose = {"A205": 0.0, "A007": 0.0}
    request = AlignmentRequest(9442.3, 1.677, 1, 0.1)

    def tick():
        preview.update(pose, pose, ("same optical settings",), request=request)

    def search():
        clicks[ALIGN] += 1
        sliders[CANDIDATE] = 0
        tick()
        assert preview.future is not None
        preview.future.result(timeout=3)
        tick()
        controls.SetSliderValue.reset_mock()

    try:
        search()
        clicks[APPLY] += 1
        tick()
        assert interference.proposed.status == InterferenceStatus.PENDING
        controls.SetSliderValue.assert_not_called()
        release.set()
        _finish_check(interference, proposed=True)
        clicks[APPLY] += 1
        tick()
        controls.SetSliderValue.assert_not_called()
        assert interference.proposed.status == (
            InterferenceStatus.UNAVAILABLE if unavailable else InterferenceStatus.INTERFERENCE
        )
        if unavailable:
            return

        sliders[CANDIDATE] = 1
        tick()
        _finish_check(interference, proposed=True)
        tick()
        assert interference.proposed.status == InterferenceStatus.CLEAR

        pose["A007"] = 0.001  # Long Jet is not an alignment axis.
        clicks[APPLY] += 1
        tick()
        controls.SetSliderValue.assert_not_called()
        controls.SetProperty.assert_any_call("/test", "alignment_frame", [AlignmentStatus.STALE])

        search()
        _finish_check(interference, proposed=True)
        tick()
        sliders[CANDIDATE] = 1
        tick()
        _finish_check(interference, proposed=True)
        tick()
        clicks[APPLY] += 1
        tick()
        controls.SetSliderValue.assert_any_call("Detector u", 1)
        controls.SetProperty.assert_any_call("/test", "alignment_frame", [AlignmentStatus.APPLIED])
    finally:
        release.set()
        preview.close()
        interference.close()


@pytest.mark.parametrize(("hits", "clear", "expected"), [
    ((812, 812, 812), None, AlignmentStatus.NO_IMPROVEMENT),
    ((0, 0, 0), None, AlignmentStatus.NO_SIGNAL),
    ((812, 812, 812), True, AlignmentStatus.NO_IMPROVEMENT),
])
def test_find_alignment_keeps_the_selected_reflection(monkeypatch, hits, clear, expected):
    controls = Mock()
    controls.GetButtonClicks.side_effect = lambda name: int(name == ALIGN)
    controls.GetSliderValue.return_value = 0  # Do not try other reflections.
    spectrometer = Mock(crystal_labels=("North", "Middle", "South"))
    spectrometer.trace.return_value = (
        None, None, [Mock(weights=np.ones(count), accepted=count) for count in hits],
    )
    clearance = None if clear is None else ClearanceSearch(Mock(return_value=clear), {}, ())
    solve, shortlist = Mock(return_value=None), Mock()
    monkeypatch.setattr("twin_lab.spectroscopy_view.find_alignment", solve)
    monkeypatch.setattr("twin_lab.spectroscopy_view.find_starting_poses", shortlist)
    preview = AlignmentPreview(controls, spectrometer, Mock(), "/test", clearance=clearance)
    positions = {}
    request = AlignmentRequest(9442.3, 1.677, 1, 0.1)
    try:
        preview.update(positions, positions, (), request=request)
        assert preview.future is not None
        assert preview.future.result(timeout=3) == expected
        preview.update(positions, positions, (), request=request)
        controls.SetProperty.assert_called_with("/test", "alignment_frame", [expected])
        assert solve.call_args.args[4] == request
        assert solve.call_args.kwargs["find_signal"] == (expected == AlignmentStatus.NO_SIGNAL)
        shortlist.assert_not_called()
        controls.SetSliderValue.assert_not_called()
    finally:
        preview.close()


@pytest.mark.parametrize("reason", [
    AlignmentStatus.NO_CLEAR_POSE, AlignmentStatus.IMPOSSIBLE, AlignmentStatus.NO_SIGNAL,
])
def test_find_alignment_previews_an_alternative_until_apply(monkeypatch, reason):
    controls = Mock()
    clicks = {ALIGN: 1}
    controls.GetButtonClicks.side_effect = lambda name: clicks.get(name, 0)
    controls.GetSliderValue.return_value = 0  # Try other reflections is unchecked.
    controls.SetSliderValue.side_effect = lambda label, _: order.append(label)
    axis = AlignmentAxis("A205", "Detector u", -12.5, 12.5, lambda x: x, lambda x: x)
    rig = AlignmentRig((axis,), (), dict.update, dict.copy)
    spectrometer = Mock(crystal_labels=("North", "Middle", "South"))
    spectrometer.trace.return_value = (
        None, None, [Mock(weights=np.zeros(0), accepted=0)] * 3,
    )
    clearance = ClearanceSearch(Mock(return_value=True), {}, ())
    hits = AlignmentImage(np.zeros((1, 1)), np.zeros(2), np.ones(2), (812,) * 3, (812,) * 3)
    candidate = StartingPose(3, AlignmentResult((0,), (1,), (0, 0), hits, hits))
    order = []

    def selected(*args, **kwargs):
        order.append("selected")
        assert kwargs["find_signal"]
        if reason == AlignmentStatus.NO_CLEAR_POSE:
            kwargs["on_interference"]()

    def shortlist(*args, progress, alternatives_only, **kwargs):
        order.append("alternatives")
        assert alternatives_only
        progress((1, 4, candidate.reflection))
        return [candidate]

    monkeypatch.setattr("twin_lab.spectroscopy_view.find_alignment", selected)
    monkeypatch.setattr("twin_lab.spectroscopy_view.find_starting_poses", shortlist)
    preview = AlignmentPreview(controls, spectrometer, rig, "/test", clearance=clearance)
    pose = {"A205": 0.0}
    spacing = 0.3 if reason == AlignmentStatus.IMPOSSIBLE else 1.677
    request = AlignmentRequest(6403.84, spacing, 1, 0.1)

    def tick():
        preview.update(pose, pose, (), request=request)

    try:
        tick()
        assert preview.future is not None
        assert preview.future.result(timeout=3) == [candidate]
        assert preview.progress.get_nowait() == (reason,)
        tick()
        assert order == (
            ["alternatives"] if reason == AlignmentStatus.IMPOSSIBLE
            else ["selected", "alternatives"]
        ) + [CANDIDATE]
        assert preview.proposal is candidate.alignment
        clicks[APPLY] = 1
        tick()
        assert order[-2:] == ["Detector u", REFLECTION]
        controls.SetSliderValue.assert_any_call("Detector u", 1)
        controls.SetSliderValue.assert_any_call(REFLECTION, candidate.reflection)
    finally:
        preview.close()


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


def test_aiming_guide_tracks_detector_without_bragg_hits():
    x, y, z = np.eye(3)
    source = Plane(np.zeros(3), z, 0.010)
    crystal = CrystalFace(
        z * 0.1 + y * 0.030,
        np.array([(x + z) / math.sqrt(2), -y, (x - z) / math.sqrt(2)]),
        (0.020, 0.006),
    )
    center = (x + z) * 0.1
    offsets = disk_offsets(source.radius_m)
    for angle in (math.pi / 4, math.pi / 4 + 0.01):
        on_axis = trace_flat(source, crystal, Detector(center, z, y, -x), offsets, angle, 1e-4)
        shifted = trace_flat(
            source, crystal, Detector(center + y * 0.040, z, y, -x), offsets, angle, 1e-4,
        )
        for trace in (on_axis, shifted):
            assert trace.accepted == len(trace.weights) == 0
        np.testing.assert_allclose(on_axis.geometric_uv_m, [0, 0], atol=1e-12)
        np.testing.assert_allclose(shifted.geometric_uv_m, [0, -0.040], atol=1e-12)
    behind = trace_flat(source, crystal, Detector(z * 0.1 - x * 0.1, z, y, -x),
                        offsets, math.pi / 4, 1e-4)
    assert behind.geometric_uv_m is None


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
    _, sensor, traces = model.trace(proposed, energy, spacing, 1, width)
    assert tuple(len(trace.weights) for trace in traces) == best.after.hits
    # Trim shifts sensor coordinates, not the diffracted rays in world space.
    for key, displacement, spot_shift in (
        ("A205", sensor.u, [-1, 0]),
        ("A206", -sensor.v, [0, 1]),
    ):
        shifted_pose = {**proposed, key: proposed[key] + 0.001}
        _, moved, trimmed = model.trace(shifted_pose, energy, spacing, 1, width)
        np.testing.assert_allclose(moved.center_m - sensor.center_m, displacement * 0.001,
                                   atol=1e-12)
        assert [len(trace.weights) for trace in trimmed] == [len(trace.weights) for trace in traces]
        _, centroid, _ = detector_image(trimmed)
        assert centroid is not None and best.after.centroid_mm is not None
        np.testing.assert_allclose(centroid - best.after.centroid_mm, spot_shift, atol=1e-9)
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

    assert_target_edits_move_the_detector_only(model, rig, home, proposed)


@pytest.mark.parametrize(("has_clear_endpoint", "quick"), [
    (True, False), (False, False), (True, True),
])
def test_pt_search_tries_alternatives_when_optical_winner_is_blocked(has_clear_endpoint, quick):
    scene = CACHE_ROOT / "stage-cad" / "DSG-000040389.43841-stage-stack" / "scene.yaml"
    if not scene.exists():
        pytest.skip("requires the local 43841 CAD cache from --spectroscopy --prepare-only")
    model = load_spectrometer(scene)
    rig = model.rig()
    caps = [joint for path in model.paths for joint in path.source_chain]
    joints = [*caps, *model.detector_chain, *(j for p in model.paths for j in p.crystal_chain)]
    home = {joint["key"]: joint["home"] for joint in joints}
    # Start with a cap moved: the search must try reviewed home, not just lock current settings.
    pose = {**home, "A231:z": -0.001, "A007": 0.002}
    checks = []
    rejected = Mock()

    def allows(endpoint, _cancel):
        assert endpoint["A007"] == pose["A007"]
        allowed = endpoint["A206"] == home["A206"] and all(
            endpoint[joint["key"]] == joint["home"] for joint in caps
        )
        checks.append(allowed)
        return has_clear_endpoint and allowed

    request = AlignmentRequest(
        LINES[0][1], model.reflections[0].spacing_a, 1, DEFAULT_HALF_WIDTH_DEG,
    )
    result = find_alignment(
        pose, model, rig, pose, request, Event(), find_signal=True,
        clearance=model.clearance_search(allows), quick=quick, on_interference=rejected,
    )
    assert checks[0] is False and any(checks)
    assert rejected.call_count == sum(not (has_clear_endpoint and allowed) for allowed in checks)
    if quick:
        assert checks == [False, True]  # No wider trial after the clear, well-captured result.
    assert pose["A231:z"] == -0.001
    if has_clear_endpoint:
        assert result is not None
        assert result.after.hits == (812, 812, 812)
        assert allows(rig.endpoint(pose, result.target), Event())
    else:
        assert result is None


def assert_target_edits_move_the_detector_only(model, rig, home, proposed):
    controls = Mock()
    sliders = {}
    axes = {axis.key: axis for axis in rig.shared}
    controls.AddSlider.side_effect = lambda name, low, high, step, initial: sliders.update(
        {name: initial}
    )
    controls.GetSliderValue.side_effect = sliders.__getitem__
    controls.GetButtonClicks.return_value = 0
    preview = SpectroscopyPreview(
        controls, model, rig, root="/test", lines=LINES,
        default_half_width_deg=DEFAULT_HALF_WIDTH_DEG, detector_target_axes=DETECTOR_TARGET_AXES,
    )
    try:
        preview.update(home, home)
        sliders[TARGET_U] = 4
        preview.update(home, home)
        controls.SetSliderValue.assert_not_called()
        controls.SetProperty.assert_any_call(
            "/test", "target_move_status", float(TargetMoveStatus.NO_SIGNAL),
        )

        # Finding/applying a pose (or dragging a slider) must not reissue an unchanged target.
        pose = proposed.copy()
        preview.update(pose, pose)
        controls.SetSliderValue.assert_not_called()
        for field, stage, target, i in ((TARGET_U, "A205", 3, 0), (TARGET_V, "A206", 2, 1)):
            sliders[field] = target
            preview.update(pose, pose)
            controls.SetSliderValue.assert_called_once()
            label, value = controls.SetSliderValue.call_args.args
            controls.SetSliderValue.reset_mock()
            assert label == axes[stage].label
            pose[stage] = axes[stage].from_slider(value)
            _, _, traces = model.trace(
                pose, LINES[0][1], model.reflections[0].spacing_a, 1, DEFAULT_HALF_WIDTH_DEG,
            )
            _, centroid, _ = detector_image(traces)
            assert centroid is not None
            assert centroid[i] == pytest.approx(target, abs=0.03)
            preview.update(pose, pose)
            controls.SetSliderValue.assert_not_called()

        sliders[TARGET_U] = -19
        preview.update(pose, pose)
        controls.SetSliderValue.assert_called_once_with(axes["A205"].label, 12.5)
        controls.SetProperty.assert_any_call(
            "/test", "target_move_status", float(TargetMoveStatus.TRAVEL_LIMIT),
        )
    finally:
        preview.close()
