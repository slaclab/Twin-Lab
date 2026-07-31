from __future__ import annotations

import pytest

pytest.importorskip("pydrake")

from twin_lab.scene import load_scene  # noqa: E402

SCENE = "tests/fixtures/three-stage-demo.dmd.yaml"


def test_model_directives_compose_three_reusable_stages() -> None:
    scene = load_scene(SCENE)

    assert scene.plant.num_model_instances() == 5  # world, default, and three stages
    assert scene.plant.num_positions() == 9
    assert scene.plant.HasModelInstanceNamed("stage_left")
    assert scene.plant.HasModelInstanceNamed("stage_center")
    assert scene.plant.HasModelInstanceNamed("stage_right")


def test_scene_reports_clearance_then_interference() -> None:
    scene = load_scene(SCENE)
    context = scene.create_context()

    at_home = scene.signed_distances(context, max_distance_m=0.1)
    assert at_home
    assert min(report.distance_m for report in at_home) > 0.0

    scene.set_joint_positions(
        context,
        {
            "stage_left::x": 0.05,
            "stage_center::x": -0.05,
        },
    )
    moved = scene.signed_distances(context, max_distance_m=0.1)
    assert min(report.distance_m for report in moved) < 0.0
