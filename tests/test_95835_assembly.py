"""Local VH assembly ownership and pose-dependent CAD clearance regressions."""

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


def test_cad_check_applies_rotation_and_metre_to_millimetre_translation(cad_model):
    model, pose, _ = cad_model
    pose[:3, :3] = np.diag([-1.0, -1.0, 1.0])
    pose[:3, 3] = [0.031, 0.01, 0.0]

    assert model.report().clearances[0].distance_m == pytest.approx(0.0005)
    pose[0, 3] = 0.030
    assert model.report().interference