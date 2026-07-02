import pytest

from slac_robotics.collision import detect_interferences
from slac_robotics.examples import build_polycap_spectrometer_model, nominal_state
from slac_robotics.model import (
    JointKind,
    SpectrometerModel,
    Stage,
    StageLimit,
    StageStack,
    collision_pair,
)


def test_nominal_polycap_example_has_no_unfiltered_interference() -> None:
    model = build_polycap_spectrometer_model()
    collisions = detect_interferences(model, nominal_state(model))

    assert collisions == []


def test_detects_expected_body_pair_interference() -> None:
    model = _two_box_model()
    state = {"left_x": 0.25, "right_x": 0.0}

    collisions = detect_interferences(model, state)
    pairs = {frozenset((collision.a, collision.b)) for collision in collisions}

    assert pairs == {frozenset(("left_body", "right_body"))}


def test_collision_filters_suppress_intentional_body_pair() -> None:
    model = _two_box_model(collision_filters=frozenset({collision_pair("left_body", "right_body")}))
    state = {"left_x": 0.25, "right_x": 0.0}

    collisions = detect_interferences(model, state)

    assert collisions == []


def test_rejects_state_outside_joint_limit() -> None:
    model = _two_box_model()

    with pytest.raises(ValueError, match="outside"):
        detect_interferences(model, {"left_x": 2.0, "right_x": 0.0})


def test_rejects_unknown_state_key() -> None:
    model = _two_box_model()

    with pytest.raises(ValueError, match="Unknown"):
        detect_interferences(model, {"left_x": 0.0, "right_x": 0.0, "typo": 0.0})


def test_detects_chamber_violation() -> None:
    model = SpectrometerModel(
        stacks=[
            StageStack(
                name="wall_test",
                base_offset=(0.20, 0.0, 0.0),
                stages=[
                    Stage.from_box(
                        name="x",
                        body_name="body",
                        kind=JointKind.LINEAR,
                        axis=(1.0, 0.0, 0.0),
                        limit=StageLimit(0.0, 0.0),
                        bbox_size=(0.10, 0.10, 0.10),
                    )
                ],
            )
        ],
        chamber_size=(0.30, 1.0, 1.0),
    )

    collisions = detect_interferences(model, {"x": 0.0})

    assert len(collisions) == 1
    assert collisions[0].a == "body"
    assert collisions[0].b == "chamber"
    assert collisions[0].overlap_xyz[0] > 0.0


def _two_box_model(
    collision_filters=frozenset(),
) -> SpectrometerModel:
    return SpectrometerModel(
        stacks=[
            StageStack(
                name="left_stack",
                stages=[
                    Stage.from_box(
                        name="left_x",
                        body_name="left_body",
                        kind=JointKind.LINEAR,
                        axis=(1.0, 0.0, 0.0),
                        limit=StageLimit(-1.0, 1.0),
                        bbox_size=(0.10, 0.10, 0.10),
                    )
                ],
            ),
            StageStack(
                name="right_stack",
                base_offset=(0.30, 0.0, 0.0),
                stages=[
                    Stage.from_box(
                        name="right_x",
                        body_name="right_body",
                        kind=JointKind.LINEAR,
                        axis=(1.0, 0.0, 0.0),
                        limit=StageLimit(0.0, 0.0),
                        bbox_size=(0.10, 0.10, 0.10),
                    )
                ],
            ),
        ],
        chamber_size=(2.0, 2.0, 2.0),
        collision_filters=collision_filters,
    )
