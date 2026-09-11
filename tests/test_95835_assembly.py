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
ELECTRONICS = {"P1209", "P1210", "P1211", "P1213", "P1214", "P1218", "P1220", "P1221"}


def test_top_electronics_ride_the_lift_and_are_not_omitted():
    review = yaml.safe_load((ASSEMBLY / "reviews" / "assembly.yaml").read_text())
    owners = {
        part if isinstance(part, str) else part["ref"]: body
        for body, spec in review["bodies"].items()
        for part in spec["parts"]
    }
    omitted = {ref for refs in review["omitted_occurrences"].values() for ref in refs}

    assert all(owners[ref] == owners["P920"] == "parker_lift" for ref in ELECTRONICS)
    assert ELECTRONICS.isdisjoint(omitted)


def test_complete_von_hamos_controls_assembly_is_retained_on_its_mounts():
    review = yaml.safe_load((ASSEMBLY / "reviews" / "assembly.yaml").read_text())
    entries = json.loads((ASSEMBLY / "manifest.json").read_text())["occurrences"]
    assembly = next(entry for entry in entries if entry["name"] == "DSG-000108873")
    controls = {
        entry["ref"] for entry in entries
        if entry["id"].startswith(assembly["id"] + "/") and not entry["is_assembly"]
    }
    assert len(controls) == 33
    required = controls | {"P1043", "P1044"}
    for ref in required:
        owners = [
            body for body, spec in review["bodies"].items()
            for part in spec["parts"]
            if (part if isinstance(part, str) else part["ref"]) == ref
        ]
        assert owners == ["parker_lift"], ref
    omitted = {ref for refs in review["omitted_occurrences"].values() for ref in refs}
    assert required.isdisjoint(omitted)


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
    entries = json.loads((ASSEMBLY / "manifest.json").read_text())["occurrences"]
    review = yaml.safe_load((ASSEMBLY / "reviews" / "assembly.yaml").read_text())
    stacks = [entry for entry in entries if entry["name"] == "mo39154771"]
    assert len(stacks) == 3
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


def test_cad_gap_clears_hull_overlap_and_caches_unchanged_pose(cad_model):
    model, _, calls = cad_model

    report = model.report(warn_m=0.001)

    assert report.status == "close"
    assert report.clearances[0].distance_m == pytest.approx(0.0005)
    assert model.report(warn_m=0.001) == report
    assert len(calls) == 2
    assert model.report(warn_m=0.0001).status == "clear"


def test_cad_check_does_not_ignore_home_pairs_after_motion(cad_model):
    model, pose, _ = cad_model
    assert not model.report().interference

    pose[0, 3] = -0.001
    report = model.report()

    assert report.interference
    assert report.clearances[0].distance_m == -0.002
    pose[0, 3] = 0.0
    assert not model.report().interference
    assert len(model._cad_gaps) == 1


def test_cad_gap_is_reused_for_common_rigid_motion_but_not_relative_motion(cad_model):
    model, pose, calls = cad_model
    assert not model.report().interference
    clearance = model.scene.signed_distances()[0]
    common = np.eye(4)
    common[:3, :3] = np.diag([-1.0, -1.0, 1.0])
    common[:3, 3] = [0.12, -0.03, 0.05]
    clearance.pose_a[:] = common
    pose[:] = common

    assert model.report().clearances[0].distance_m == pytest.approx(0.0005)
    assert len(calls) == 2

    pose[0, 3] += 0.001
    assert model.report().interference
    assert len(calls) == 4


def test_cad_check_applies_rotation_and_metre_to_millimetre_translation(cad_model):
    model, pose, _ = cad_model
    pose[:3, :3] = np.diag([-1.0, -1.0, 1.0])
    pose[:3, 3] = [0.031, 0.01, 0.0]

    assert model.report().clearances[0].distance_m == pytest.approx(0.0005)
    pose[0, 3] = 0.030
    assert model.report().interference


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

    report = model.report(warn_m=0.0)

    assert report.interference == (layout != "inside_cavity")