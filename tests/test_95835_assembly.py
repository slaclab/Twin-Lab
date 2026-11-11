"""Local VH assembly ownership and pose-dependent CAD clearance regressions."""

import json
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import yaml

from twin_lab.collision import Clearance

ASSEMBLY = Path(__file__).resolve().parents[1] / "cad" / "DSG-000095835"


def _review():
    return yaml.safe_load((ASSEMBLY / "reviews" / "assembly.yaml").read_text())


def _manifest():
    return json.loads((ASSEMBLY / "manifest.json").read_text())["occurrences"]


def _refs(name, entries=None):
    """Leaf refs whose CAD name, without Solid Edge's ``_oa_`` suffix, is ``name``.

    Refs are renumbered by every STEP export, so tests find parts by name.
    """
    return [
        entry["ref"] for entry in (entries or _manifest())
        if not entry["is_assembly"] and entry["name"].split("_oa_")[0] == name
    ]


def _owners(review):
    return {
        part if isinstance(part, str) else part["ref"]: body
        for body, spec in review["bodies"].items()
        for part in spec["parts"]
        if isinstance(part, str) or "region" not in part
    }


def _omitted(review):
    return {ref for refs in review["omitted_occurrences"].values() for ref in refs}


def test_controls_envelope_and_posts_ride_the_lift_and_are_not_omitted():
    review = _review()
    entries = _manifest()
    owners = _owners(review)
    # Lift plate mo39154769, the user-supplied controls envelope and its four support posts.
    plate = _refs("mo39154769", entries)
    envelope = [
        entry["ref"] for entry in entries
        if entry["name"].startswith("REF__mo39154780-_UserSuppliedControls")
    ]
    posts = _refs("Thorlabs__PillarPostExtension_1.00Dx3.00L__RS3", entries)
    assert len(plate) == 1 and len(envelope) == 1 and len(posts) == 4

    assert {owners[ref] for ref in [*plate, *envelope, *posts]} == {"parker_lift"}
    assert _omitted(review).isdisjoint([*envelope, *posts])


def test_local_viewer_defaults_to_contact_only_coloring(monkeypatch, tmp_path):
    pytest.importorskip("OCP")
    pytest.importorskip("pydrake")
    monkeypatch.syspath_prepend(str(ASSEMBLY))
    module = import_module("collision_view")
    calls = []
    monkeypatch.setattr(
        module.collision_viewer, "run_collision_viewer",
        lambda package, **options: calls.append((package, options)),
    )
    original_model = module.collision_viewer.CollisionModel

    module.view(tmp_path)

    assert calls == [(tmp_path, {"label_source": module.RECIPE, "warn_mm": 0.0})]
    assert module.collision_viewer.CollisionModel is original_model


def test_all_imported_crystal_stacks_have_reviewed_payloads():
    entries = _manifest()
    review = _review()
    stacks = [entry for entry in entries if entry["name"].split("_oa_")[0] == "mo39154771"]
    assert len(stacks) == 4
    for number, stack in enumerate(stacks, start=1):
        payloads = {
            entry["ref"] for entry in entries
            if entry["id"].startswith(stack["id"] + "/")
            and "CylinderCrystalAnalyzer" in entry["name"]
        }
        assert len(payloads) == 1
        assert payloads <= set(
            part for part in review["bodies"][f"crystal_{number}_tilt"]["parts"]
            if isinstance(part, str)
        )
        for axis in ("translation", "rotation", "tilt"):
            assert review["bodies"][f"crystal_{number}_{axis}"]["parts"]
    assert review["visual_rgba"] == [0.7, 0.7, 0.7, 1.0]
    assert review["visual_colors"] == "step"


def test_fourth_stack_joints_match_the_first_stack():
    joints = {joint["name"]: joint for joint in _review()["joints"]}
    for axis in ("translation", "rotation", "tilt"):
        first, fourth = joints[f"crystal_1_{axis}_joint"], joints[f"crystal_4_{axis}_joint"]
        assert (fourth["parent"], fourth["child"]) == (
            first["parent"].replace("crystal_1", "crystal_4"),
            first["child"].replace("crystal_1", "crystal_4"),
        )
        assert fourth["type"] == first["type"]
        assert fourth["limits"] == first["limits"]
        assert np.linalg.norm(fourth["axis_xyz"]) == pytest.approx(1.0)


def test_slit_blade_holders_and_blades_ride_their_blade_rods():
    review = _review()
    entries = _manifest()
    owners = _owners(review)
    holders = _refs("DSG-000000720", entries)
    blades = _refs("mo39143619", entries) + _refs("mo39143620", entries)
    assert len(holders) == 2 and len(blades) == 4
    assert _omitted(review).isdisjoint(holders + blades)
    # Each rod tip clamps one holder DSG-000000720 and two blade plates.
    for body, rod in (("bottom_slit_x", "DSG-000092551"), ("top_slit_x", "DSG-000092523")):
        assert {owners[ref] for ref in _refs(rod, entries)} == {body}
        assert sum(owners[ref] == body for ref in holders) == 1
        assert sum(owners[ref] == body for ref in blades) == 2


def test_analyzer_and_crystal_rotations_are_limited_to_45_degrees():
    joints = {joint["name"]: joint for joint in _review()["joints"]}
    rotations = ["analyzer_rotation_joint"] + [
        f"crystal_{number}_rotation_joint" for number in range(1, 5)
    ]
    for name in rotations:
        assert joints[name]["limits"] == pytest.approx([-np.pi / 4, np.pi / 4]), name


def test_epix_z_travel_follows_the_payload_offset_from_its_fused_carriage():
    review = _review()
    joint = next(joint for joint in review["joints"] if joint["name"] == "detector_z_joint")
    split = review["stage_splits"][joint["stage_ref"]]
    offset_m = -split["moving_offset_mm"][2] / 1000.0
    # 300 mm of travel stays centred on the carriage the fused slide models.
    assert joint["limits"] == pytest.approx([-0.15 + offset_m, 0.15 + offset_m])
    assert joint["limits"][0] < 0.0 < joint["limits"][1]


def test_epix100_rides_linear_stage_manual_kohzu_and_swivel():
    review = _review()
    entries = _manifest()
    owners = _owners(review)
    bodies = review["bodies"]
    joints = {joint["name"]: joint for joint in review["joints"]}
    (linear,) = _refs("LIB-000000725", entries)
    (kohzu,) = _refs("LIB-000005430", entries)
    (swivel_base,) = _refs("LIB-000013710", entries)
    (swivel_top,) = _refs("LIB-000013712", entries)
    (sensor,) = _refs("REF__Chip__sa39154207", entries)

    def regions(body, ref):
        return {
            part["region"] for part in bodies[body]["parts"]
            if isinstance(part, dict) and part["ref"] == ref and "region" in part
        }

    # Each fused stage is split between the body it is bolted to and the body it carries.
    assert regions("assembly_base", linear) == {"fixed"}
    assert regions("epix100_x", linear) == {"moving"}
    assert regions("epix100_x", kohzu) == {"fixed"}
    assert regions("epix100_z", kohzu) == {"moving"}
    assert owners[swivel_base] == "epix100_z" and owners[swivel_top] == "epix100_tilt"
    assert owners[sensor] == "epix100_tilt"
    chain = [("epix100_x_joint", "prismatic"), ("epix100_z_joint", "prismatic"),
             ("epix100_tilt_joint", "revolute")]
    parent = "assembly_base"
    for name, kind in chain:
        joint = joints[name]
        assert (joint["parent"], joint["type"]) == (parent, kind)
        parent = joint["child"]
    assert joints["epix100_z_joint"]["limits"] == pytest.approx([-0.0065, 0.0065])
    assert joints["epix100_tilt_joint"]["limits"] == pytest.approx([-np.pi / 18, np.pi / 18])
    templates = yaml.safe_load((ASSEMBLY / "reviews" / "stage-splits.yaml").read_text())
    assert {"LIB-000000725", "LIB-000005430"} <= set(templates)


def test_epix100_housing_and_rear_plumbing_ride_the_swivel():
    review = _review()
    entries = _manifest()
    owners = _owners(review)
    # The 14:01 export gave the covers and cooling block solids; earlier exports left them empty.
    housing = [
        ref for name in (
            "REF__sa39154258__RearCover-1", "REF__sa39154222__FrontCover-0",
            "mo39154260", "mo39154261",
        )
        for ref in _refs(name, entries)
    ]
    plumbing = [
        ref for name in (
            "Swagelok__Ftg_NutVCR.25Male__SS-4-HVCR-4SR",
            "Swagelok__Fitting_ShortSktWld__SS-4-VCR-3-.50LG",
            "mo39154264", "mo39154267", "mo39154257",
        )
        for ref in _refs(name, entries)
    ]
    assert len(housing) == 4 and len(plumbing) == 8
    assert {owners[ref] for ref in housing + plumbing} == {"epix100_tilt"}

def test_diffractometer_base_is_fixed_geometry_and_its_empty_parts_stay_omitted():
    review = _review()
    entries = _manifest()
    (base,) = _refs("REF__mo39144450__DiffractometerBase", entries)
    assert _owners(review)[base] == "assembly_base"
    # Body, 2-theta arm and 2-theta stage carry only coordinate systems in this STEP.
    empty = {
        ref for name in ("Diffractometer", "2ThetaArm", "2ThetaStage")
        for ref in _refs(f"REF__mo39144450__{name}", entries)
    }
    assert len(empty) == 3
    assert empty <= set(review["omitted_occurrences"]["Empty geometry in source STEP"])


def test_bearing_parts_sit_on_their_joint_bodies():
    review = _review()
    owned = {
        body: {part if isinstance(part, str) else part["ref"] for part in spec["parts"]}
        for body, spec in review["bodies"].items()
    }
    for joint in review["joints"]:
        fixed, moving = joint["bearing_parts"]
        assert set(fixed) <= owned[joint["parent"]], joint["name"]
        assert set(moving) <= owned[joint["child"]], joint["name"]
    joints = {joint["name"]: joint for joint in review["joints"]}
    (end_plate,) = _refs("mo39154774")
    assert end_plate in joints["analyzer_rotation_joint"]["bearing_parts"][1]


def test_step_colours_follow_split_history_onto_visual_meshes(monkeypatch, tmp_path):
    pytest.importorskip("OCP")
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.BRepTools import BRepTools

    monkeypatch.syspath_prepend(str(ASSEMBLY))
    module = import_module("build")
    monkeypatch.setattr(module, "CACHE", tmp_path)
    BRepTools.Write_s(BRepPrimAPI_MakeBox(10.0, 10.0, 10.0).Shape(), str(tmp_path / "X-local.brep"))
    transform = [[1, 0, 0, 100], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    stats = {"X": {"transform": transform}}
    red, blue = [1.0, 0.0, 0.0, 1.0], [0.0, 0.0, 1.0, 0.5]
    # MakeBox faces are x=0, x=10, y=0, y=10, z=0, z=10; -1 is a face the STEP left plain.
    partly_plain = {"palette": [red, blue], "faces": [0, 1, 1, 1, 1, -1]}
    leaf = {"palette": [red, blue], "faces": [0, 1, 1, 1, 1, 1]}
    review = {"stage_splits": {"X": {
        "source_solids": [1],
        "moving_mask": {"kind": "box", "min_mm": [5, -1, -1], "max_mm": [15, 11, 11]},
    }}}

    _, whole_colors = module.colored_shape("X", review, stats, partly_plain)
    assert sorted(map(str, whole_colors)) == sorted(
        map(str, [tuple(red), *[tuple(blue)] * 4, None])
    )
    fixed, colors = module.colored_shape({"ref": "X", "region": "fixed"}, review, stats, leaf)
    # The x=0 face survives whole, x=10 goes with the moving half, four faces are cut in
    # half, and the cut face itself is new.
    assert len(colors) == 6
    assert colors.count(tuple(red)) == 1
    assert colors.count(tuple(blue)) == 4
    assert colors.count(None) == 1

    output = tmp_path / "visual.obj"
    main = module.write_colored_obj(
        fixed, colors, (0.5, 0.5, 0.5, 1.0), "X", output, linear_deflection_mm=0.5
    )
    lines = output.read_text().splitlines()
    assert lines[0] == "mtllib visual.mtl"
    assert sum(line.startswith("usemtl ") for line in lines) == 3
    xs = [float(line.split()[1]) for line in lines if line.startswith("v ")]
    assert min(xs) == pytest.approx(0.1) and max(xs) == pytest.approx(0.105)
    material = output.with_suffix(".mtl").read_text()
    assert "Kd 0.0000 0.0000 1.0000\nd 0.5000" in material
    assert main == blue

    # A reviewed carriage offset moves only the moving half, and keeps its colours.
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    def x_range(shape):
        box = Bnd_Box()
        BRepBndLib.Add_s(shape, box, False)
        return box.Get()[0], box.Get()[3]

    moving_part = {"ref": "X", "region": "moving"}
    assert x_range(module.read_shape(moving_part, review, stats)) == pytest.approx((105, 110))
    review["stage_splits"]["X"]["moving_offset_mm"] = [-30.0, 0.0, 0.0]
    moving, moving_colors = module.colored_shape(moving_part, review, stats, leaf)
    assert x_range(moving) == pytest.approx((75, 80))
    assert x_range(module.read_shape(moving_part, review, stats)) == pytest.approx((75, 80))
    assert moving_colors.count(tuple(blue)) == 5 and moving_colors.count(None) == 1
    assert x_range(module.read_shape({"ref": "X", "region": "fixed"}, review, stats)) == (
        pytest.approx((100, 105))
    )


def test_split_templates_expand_with_reviewed_offsets(monkeypatch):
    monkeypatch.syspath_prepend(str(ASSEMBLY))
    module = import_module("build")
    templates = {"T": {"source_solids": [1]}}
    review = {"stage_splits": {"A": "T", "B": {"template": "T", "moving_offset_mm": [0, 0, 5]}}}

    assert module.expand_stage_splits(review, templates) == {
        "A": {"source_solids": [1]},
        "B": {"source_solids": [1], "moving_offset_mm": [0, 0, 5]},
    }


def test_recipe_ignored_pairs_reach_the_collision_model(cad_model):
    model, _, _ = cad_model
    (port,) = _refs("DSG-000052395")
    rods = _refs("DSG-000092551") + _refs("DSG-000092523")
    assert {tuple(sorted((port, rod))) for rod in rods} <= model.ignored_pairs


def test_jet_slit_and_detector_stages_are_driven_in_beamline_axes():
    review = yaml.safe_load((ASSEMBLY / "reviews" / "assembly.yaml").read_text())
    joints = {joint["name"]: joint for joint in review["joints"]}
    # Beamline x/y/z in world coordinates: y up, beam along -z (world -Y).
    beamline = {"x": [-1.0, 0.0, 0.0], "y": [0.0, 0.0, 1.0], "z": [0.0, 1.0, 0.0]}
    chains = {
        "lj": ["x", "z", "y"],
        "bottom_slit": ["y", "x"],
        "top_slit": ["y", "x"],
        "detector": ["z", "x"],
    }
    for prefix, axes in chains.items():
        parent = "assembly_base"
        for axis in axes:
            joint = joints[f"{prefix}_{axis}_joint"]
            assert (joint["parent"], joint["child"]) == (parent, f"{prefix}_{axis}")
            assert joint["type"] == "prismatic"
            assert joint["axis_xyz"] == beamline[axis]
            fixed, moving = joint["bearing_parts"]
            owned = {
                body: {part if isinstance(part, str) else part["ref"]
                       for part in review["bodies"][body]["parts"]}
                for body in (joint["parent"], joint["child"])
            }
            assert set(fixed) <= owned[joint["parent"]]
            assert set(moving) <= owned[joint["child"]]
            parent = joint["child"]
    assert "lj" not in review["fixed_subsystems"]


@pytest.fixture
def cad_model(monkeypatch):
    pytest.importorskip("OCP")
    pytest.importorskip("pydrake")
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt

    monkeypatch.syspath_prepend(str(ASSEMBLY))
    module = import_module("collision_view")
    monkeypatch.setattr(
        module.AssemblyCollisionModel, "_reopen_joint_adjacent_pairs", lambda self: 0
    )
    monkeypatch.setattr(
        module.AssemblyCollisionModel, "_configure_stack_interference_filters", lambda self: None
    )
    pose = np.eye(4)
    clearance = Clearance(
        "vh::support::vh::p001_collision",
        "vh::payload::vh::p002_collision",
        -0.002,
        pose_a=np.eye(4),
        pose_b=pose,
    )
    scene = SimpleNamespace(
        create_context=lambda: None,
        signed_distances=lambda *args, **kwargs: [clearance],
    )
    model = module.AssemblyCollisionModel(scene)
    shapes = {
        "support/P001": BRepPrimAPI_MakeBox(10.0, 10.0, 10.0).Shape(),
        "payload/P002": BRepPrimAPI_MakeBox(gp_Pnt(10.5, 0.0, 0.0), 10.0, 10.0, 10.0).Shape(),
    }
    calls = []

    def shape(name):
        calls.append(name)
        return shapes[name]

    monkeypatch.setattr(model, "_cad_shape", shape)
    return model, pose, calls


def test_collision_report_uses_hulls_without_loading_cad(cad_model):
    model, _, calls = cad_model

    report = model.report(warn_m=0.0)

    assert model.supports_verification
    assert model.refiner is None
    assert report.interference
    assert report.clearances[0].distance_m == -0.002
    assert calls == []
    assert model._cad_shapes == {}
    assert model._cad_gaps == {}
    assert model._cad_review is None
    assert model._cad_stats is None


def test_cad_gap_clears_hull_overlap_and_caches_unchanged_pose(cad_model):
    model, _, calls = cad_model

    report, _ = model.verify(model.report(warn_m=0.001))

    assert report.status == "close"
    assert report.clearances[0].distance_m == pytest.approx(0.0005)
    assert model.verify(model.report(warn_m=0.001))[0] == report
    assert len(calls) == 2
    assert model.verify(model.report(warn_m=0.0001))[0].status == "clear"


def test_hull_report_is_not_changed_by_previous_cad_verification(cad_model):
    model, _, calls = cad_model
    raw = model.report(warn_m=0.0)

    checked, _ = model.verify(raw)

    assert checked.status == "clear"
    assert raw.interference
    assert model.report(warn_m=0.0) == raw
    assert len(calls) == 2


def test_cad_check_does_not_ignore_home_pairs_after_motion(cad_model):
    model, pose, _ = cad_model
    assert not model.verify(model.report())[0].interference

    pose[0, 3] = -0.001
    report, _ = model.verify(model.report())

    assert report.interference
    assert report.clearances[0].distance_m == -0.002
    pose[0, 3] = 0.0
    assert not model.verify(model.report())[0].interference
    assert len(model._cad_gaps) == 1


def test_cad_gap_is_reused_for_common_rigid_motion_but_not_relative_motion(cad_model):
    model, pose, calls = cad_model
    assert not model.verify(model.report())[0].interference
    clearance = model.scene.signed_distances()[0]
    common = np.eye(4)
    common[:3, :3] = np.diag([-1.0, -1.0, 1.0])
    common[:3, 3] = [0.12, -0.03, 0.05]
    clearance.pose_a[:] = common
    pose[:] = common

    assert model.verify(model.report())[0].clearances[0].distance_m == pytest.approx(0.0005)
    assert len(calls) == 2

    pose[0, 3] += 0.001
    assert model.verify(model.report())[0].interference
    assert len(calls) == 4


def test_cad_check_applies_rotation_and_metre_to_millimetre_translation(cad_model):
    model, pose, _ = cad_model
    pose[:3, :3] = np.diag([-1.0, -1.0, 1.0])
    pose[:3, 3] = [0.031, 0.01, 0.0]

    assert model.verify(model.report())[0].clearances[0].distance_m == pytest.approx(0.0005)
    pose[0, 3] = 0.030
    assert model.verify(model.report())[0].interference


@pytest.mark.parametrize("layout", ["contained", "contained_reversed", "inside_cavity"])
def test_cad_compounds_preserve_containment_but_clear_real_cavities(cad_model, monkeypatch, layout):
    from OCP.BRep import BRep_Builder
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    from OCP.TopoDS import TopoDS_Compound

    model, _, _ = cad_model
    outer = BRepPrimAPI_MakeBox(10.0, 10.0, 10.0).Shape()
    inner = BRepPrimAPI_MakeBox(gp_Pnt(2.0, 2.0, 2.0), 2.0, 2.0, 2.0).Shape()
    if layout == "inside_cavity":
        cavity = BRepPrimAPI_MakeBox(gp_Pnt(1.0, 1.0, 1.0), 8.0, 8.0, 8.0).Shape()
        outer = BRepAlgoAPI_Cut(outer, cavity).Shape()
    shapes = [outer, inner] if layout != "contained_reversed" else [inner, outer]
    selections = {}
    for name, shape in zip(("support/P001", "payload/P002"), shapes, strict=True):
        compound = TopoDS_Compound()
        builder = BRep_Builder()
        builder.MakeCompound(compound)
        builder.Add(compound, shape)
        selections[name] = compound
    monkeypatch.setattr(model, "_cad_shape", selections.__getitem__)

    report, _ = model.verify(model.report(warn_m=0.0))

    assert report.interference == (layout != "inside_cavity")


def test_targeted_refinement_selects_overshoot_gaps_and_home_contacts(monkeypatch):
    monkeypatch.syspath_prepend(str(ASSEMBLY))
    module = import_module("refine_hulls")
    baseline = [
        {"source": "cage", "part_ref": "P526", "max_bulge_mm": 11.0, "max_gap_mm": 0.0},
        {"source": "good", "part_ref": "P001", "max_bulge_mm": 0.1, "max_gap_mm": 0.0},
        {"source": "home", "part_ref": "P936", "max_bulge_mm": 0.4, "max_gap_mm": 0.0},
        {"source": "gap", "part_ref": "P699", "max_bulge_mm": 0.2, "max_gap_mm": 0.4},
    ]

    assert [item["source"] for item in module.select_targets(baseline)] == ["cage", "home", "gap"]


@pytest.mark.parametrize("defect", [None, "coverage", "volume", "bulge", "empty", "nonfinite"])
def test_refinement_only_recommends_measured_improvements(monkeypatch, defect):
    monkeypatch.syspath_prepend(str(ASSEMBLY))
    module = import_module("refine_hulls")
    baseline = {"max_bulge_mm": 10.0, "hull_volume_m3": 1.0}
    audit = {
        "max_bulge_mm": 1.0, "max_gap_mm": 0.0, "outside_fraction": 0.0,
        "hull_volume_m3": 0.9, "hull_count": 4,
    }
    if defect == "coverage":
        audit["max_gap_mm"] = 0.01
    elif defect == "volume":
        audit["hull_volume_m3"] = 1.1
    elif defect == "bulge":
        audit["max_bulge_mm"] = 9.5
    elif defect == "empty":
        audit["hull_count"] = 0
    elif defect == "nonfinite":
        audit["max_bulge_mm"] = float("nan")
    candidate = {"status": "ok", "audit": audit, "resolution": 200}

    best = module.best_candidate(baseline, [candidate, {"status": "failed"}])

    assert best is (candidate if defect is None else None)


def test_refinement_batch_checkpoints_failures_and_resumes_without_repeating(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(ASSEMBLY))
    module = import_module("refine_hulls")
    args = SimpleNamespace(
        output=tmp_path, resolutions=[200, 400], target_mm=0.5,
        memory_gb=10.0, part_timeout_s=30.0,
    )
    targets = [
        {"source": str(tmp_path / f"{name}.obj"), "part_ref": name,
         "max_bulge_mm": 3.0, "max_gap_mm": 0.1, "hull_volume_m3": 1.0, "hull_count": 4}
        for name in ("good", "broken")
    ]
    calls = []

    def run(command, **options):
        source = Path(command[command.index("--worker-source") + 1])
        resolution = int(command[command.index("--worker-resolution") + 1])
        calls.append((source.stem, resolution))
        assert options["timeout"] == 30.0
        assert options["env"]["OMP_NUM_THREADS"] == "2"
        if source.stem == "broken":
            raise module.subprocess.TimeoutExpired(command, 30.0)
        result = {
            "status": "ok", "resolution": resolution, "cache": str(tmp_path / "candidate"),
            "audit": {"max_bulge_mm": 0.2, "max_gap_mm": 0.0, "outside_fraction": 0.0,
                      "hull_volume_m3": 0.8, "hull_count": 4},
        }
        module.write_json(tmp_path / f"{source.stem}.{resolution}.json", result)

    monkeypatch.setattr(module.subprocess, "run", run)

    module.run_batch(args, targets)
    module.run_batch(args, targets)

    assert calls == [("good", 200), ("broken", 200)]
    state = json.loads((tmp_path / "results.json").read_text())
    assert state["status"] == "completed"
    assert state["results"]["broken"][0]["status"] == "failed"
    assert (tmp_path / "comparison.csv").exists()


@pytest.mark.parametrize("fault", ["running", "recipe", "sources", "mesh"])
def test_candidate_build_rejects_changed_refinement_inputs(monkeypatch, tmp_path, fault):
    import hashlib

    monkeypatch.syspath_prepend(str(ASSEMBLY))
    module = import_module("refine_hulls")
    source = tmp_path / "part.obj"
    source.write_text("original")
    recipe = b"reviewed recipe"
    plan = {
        "recipe_sha256": hashlib.sha256(recipe).hexdigest(), "targets": [],
        "source_sha256": {str(source): hashlib.sha256(b"original").hexdigest()},
    }
    state = {"status": "completed", "results": {}}
    sources = {source}
    if fault == "running":
        state["status"] = "running"
    elif fault == "recipe":
        recipe = b"different recipe"
    elif fault == "sources":
        sources = set()
    elif fault == "mesh":
        source.write_text("modified")
    module.write_json(tmp_path / "plan.json", plan)
    module.write_json(tmp_path / "results.json", state)

    with pytest.raises(ValueError):
        module.candidate_parts(tmp_path, sources, recipe)


def test_refined_build_cannot_replace_active_export(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(ASSEMBLY))
    module = import_module("build")
    monkeypatch.setattr(module, "EXPORT_ROOT", tmp_path)

    with pytest.raises(ValueError, match="separate output"):
        module.build(collision="convex", refinement_run=tmp_path / "run",
                     output_dir=tmp_path / "DSG-000095835.collision")