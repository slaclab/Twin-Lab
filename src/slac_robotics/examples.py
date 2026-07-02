"""Starter examples for XCS polycapillary-style spectrometer layouts."""

from __future__ import annotations

from itertools import combinations
import math
from typing import Dict, Iterable

from .collision import detect_interferences
from .model import (
    CollisionPair,
    JointKind,
    SpectrometerModel,
    Stage,
    StageLimit,
    StageStack,
    collision_pair,
)


def build_polycap_spectrometer_model() -> SpectrometerModel:
    """
    Build a rough 7-stack model:
    - 1 detector stack
    - 3 crystal stacks
    - 3 polycapillary stacks

    Geometry sizes and offsets are placeholders; replace using CAD measurements.
    """

    detector = StageStack(
        name="detector_stack",
        base_offset=(0.55, 0.0, 0.0),
        stages=[
            Stage.from_box(
                name="det_x",
                body_name="det_x_carriage",
                kind=JointKind.LINEAR,
                axis=(1.0, 0.0, 0.0),
                limit=StageLimit(-0.08, 0.08),
                bbox_size=(0.20, 0.14, 0.10),
            ),
            Stage.from_box(
                name="det_y",
                body_name="det_y_carriage",
                kind=JointKind.LINEAR,
                axis=(0.0, 1.0, 0.0),
                limit=StageLimit(-0.04, 0.04),
                bbox_size=(0.20, 0.14, 0.10),
            ),
        ],
    )

    crystal_stacks = []
    for i, y in enumerate((-0.18, 0.0, 0.18), start=1):
        crystal_stacks.append(
            StageStack(
                name=f"crystal_stack_{i}",
                base_offset=(0.25, y, 0.0),
                stages=[
                    Stage.from_box(
                        name=f"cry{i}_theta",
                        body_name=f"cry{i}_theta_plate",
                        kind=JointKind.ROTARY,
                        axis=(0.0, 0.0, 1.0),
                        limit=StageLimit(math.radians(-30), math.radians(30)),
                        bbox_size=(0.10, 0.10, 0.08),
                    ),
                    Stage.from_box(
                        name=f"cry{i}_x",
                        body_name=f"cry{i}_x_carriage",
                        kind=JointKind.LINEAR,
                        axis=(1.0, 0.0, 0.0),
                        limit=StageLimit(-0.03, 0.03),
                        bbox_size=(0.11, 0.11, 0.09),
                        mount_offset=(0.03, 0.0, 0.0),
                    ),
                ],
            )
        )

    polycap_stacks = []
    for i, y in enumerate((-0.16, 0.02, 0.20), start=1):
        polycap_stacks.append(
            StageStack(
                name=f"polycap_stack_{i}",
                base_offset=(-0.10, y, 0.0),
                stages=[
                    Stage.from_box(
                        name=f"poly{i}_z",
                        body_name=f"poly{i}_z_carriage",
                        kind=JointKind.LINEAR,
                        axis=(0.0, 0.0, 1.0),
                        limit=StageLimit(-0.05, 0.05),
                        bbox_size=(0.11, 0.10, 0.11),
                    ),
                    Stage.from_box(
                        name=f"poly{i}_gonio",
                        body_name=f"poly{i}_gonio_cradle",
                        kind=JointKind.GONIO,
                        axis=(0.0, 1.0, 0.0),
                        limit=StageLimit(math.radians(-8), math.radians(8)),
                        bbox_size=(0.12, 0.11, 0.12),
                        mount_offset=(0.0, 0.0, 0.03),
                    ),
                ],
            )
        )

    stacks = [detector] + crystal_stacks + polycap_stacks
    return SpectrometerModel(
        stacks=stacks,
        chamber_size=(1.30, 0.65, 0.50),
        collision_filters=_same_stack_filters(stacks),
    )


def nominal_state(model: SpectrometerModel) -> Dict[str, float]:
    """Construct a valid state at each joint's home position."""

    return {joint.name: joint.home for joint in model.all_joints()}


def _same_stack_filters(stacks: Iterable[StageStack]) -> frozenset[CollisionPair]:
    """Ignore body pairs intentionally assembled in the same coarse stack."""

    pairs: set[CollisionPair] = set()
    for stack in stacks:
        for first, second in combinations(stack.body_names(), 2):
            pairs.add(collision_pair(first, second))
    return frozenset(pairs)


def demo() -> None:
    model = build_polycap_spectrometer_model()
    state = nominal_state(model)
    state["det_x"] = -0.04
    state["cry2_theta"] = math.radians(15)
    state["poly1_gonio"] = math.radians(6)

    collisions = detect_interferences(model, state)
    if not collisions:
        print("No interference detected.")
        return

    print("Interference report:")
    for collision in collisions:
        ox, oy, oz = collision.overlap_xyz
        print(f"- {collision.a} vs {collision.b} " f"(x={ox:.4f} m, y={oy:.4f} m, z={oz:.4f} m)")


if __name__ == "__main__":
    demo()
