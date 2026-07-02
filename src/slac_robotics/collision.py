"""Conservative interference checks for stage-stack systems."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Dict, List, Tuple

from .model import Joint, JointKind, SpectrometerModel, Vec3
from .transforms import (
    Mat4,
    gonio_motion,
    matmul,
    move_along_axis,
    rotate_about_axis,
    transform_point,
    translate,
)


@dataclass(frozen=True)
class CollisionReport:
    """Result for one pairwise interference check."""

    a: str
    b: str
    overlap_xyz: Vec3


@dataclass(frozen=True)
class PlacedBody:
    """A body geometry placed in world coordinates."""

    name: str
    stack_name: str
    joint_name: str
    world_tf: Mat4
    bbox_size: Vec3


def _joint_motion_tf(joint: Joint, value: float) -> Mat4:
    if joint.kind == JointKind.LINEAR:
        return move_along_axis(joint.axis, value)
    if joint.kind == JointKind.ROTARY:
        return rotate_about_axis(joint.axis, value)
    if joint.kind == JointKind.GONIO:
        return gonio_motion(joint.axis, value)
    raise ValueError(f"Unsupported joint kind: {joint.kind}")


def _box_corners(size_xyz: Vec3) -> List[Vec3]:
    sx, sy, sz = size_xyz
    hx, hy, hz = sx / 2.0, sy / 2.0, sz / 2.0
    return [
        (-hx, -hy, -hz),
        (+hx, -hy, -hz),
        (-hx, +hy, -hz),
        (+hx, +hy, -hz),
        (-hx, -hy, +hz),
        (+hx, -hy, +hz),
        (-hx, +hy, +hz),
        (+hx, +hy, +hz),
    ]


def _world_aabb(world_tf: Mat4, size_xyz: Vec3) -> Tuple[Vec3, Vec3]:
    corners = _box_corners(size_xyz)
    world_pts = [transform_point(world_tf, corner) for corner in corners]

    min_x = min(pt[0] for pt in world_pts)
    min_y = min(pt[1] for pt in world_pts)
    min_z = min(pt[2] for pt in world_pts)
    max_x = max(pt[0] for pt in world_pts)
    max_y = max(pt[1] for pt in world_pts)
    max_z = max(pt[2] for pt in world_pts)
    return (min_x, min_y, min_z), (max_x, max_y, max_z)


def _aabb_overlap(
    a_min: Vec3,
    a_max: Vec3,
    b_min: Vec3,
    b_max: Vec3,
) -> Tuple[bool, Vec3]:
    overlap = (
        min(a_max[0], b_max[0]) - max(a_min[0], b_min[0]),
        min(a_max[1], b_max[1]) - max(a_min[1], b_min[1]),
        min(a_max[2], b_max[2]) - max(a_min[2], b_min[2]),
    )
    return (overlap[0] > 0.0 and overlap[1] > 0.0 and overlap[2] > 0.0), overlap


def place_bodies(model: SpectrometerModel, state: Dict[str, float]) -> List[PlacedBody]:
    """Return every collision body in world coordinates."""

    model.validate_state(state)
    placed: List[PlacedBody] = []

    for stack in model.stacks:
        chain_tf = translate(stack.base_offset)
        for stage in stack.stages:
            joint = stage.joint
            chain_tf = matmul(chain_tf, translate(joint.parent_offset))
            chain_tf = matmul(chain_tf, _joint_motion_tf(joint, state[joint.name]))

            for body in stage.bodies:
                body_tf = matmul(chain_tf, translate(body.geometry.local_offset))
                placed.append(
                    PlacedBody(
                        name=body.name,
                        stack_name=stack.name,
                        joint_name=joint.name,
                        world_tf=[row[:] for row in body_tf],
                        bbox_size=body.geometry.size,
                    )
                )

    return placed


def detect_interferences(
    model: SpectrometerModel, state: Dict[str, float]
) -> List[CollisionReport]:
    """Return all pairwise body-body and body-chamber interference events."""

    placed = place_bodies(model, state)
    reports: List[CollisionReport] = []
    aabbs = {body.name: _world_aabb(body.world_tf, body.bbox_size) for body in placed}

    for first, second in combinations(placed, 2):
        if model.is_collision_filtered(first.name, second.name):
            continue

        a_min, a_max = aabbs[first.name]
        b_min, b_max = aabbs[second.name]
        intersects, overlap = _aabb_overlap(a_min, a_max, b_min, b_max)
        if intersects:
            reports.append(
                CollisionReport(
                    a=first.name,
                    b=second.name,
                    overlap_xyz=(float(overlap[0]), float(overlap[1]), float(overlap[2])),
                )
            )

    reports.extend(_detect_chamber_violations(model, placed, aabbs))
    return reports


def _detect_chamber_violations(
    model: SpectrometerModel,
    placed: List[PlacedBody],
    aabbs: Dict[str, Tuple[Vec3, Vec3]],
) -> List[CollisionReport]:
    # Chamber is centered at world origin.
    c_half = (
        model.chamber_size[0] / 2.0,
        model.chamber_size[1] / 2.0,
        model.chamber_size[2] / 2.0,
    )
    c_min = (-c_half[0], -c_half[1], -c_half[2])
    c_max = (c_half[0], c_half[1], c_half[2])

    reports: List[CollisionReport] = []
    for body in placed:
        s_min, s_max = aabbs[body.name]
        outside = (
            s_min[0] < c_min[0]
            or s_min[1] < c_min[1]
            or s_min[2] < c_min[2]
            or s_max[0] > c_max[0]
            or s_max[1] > c_max[1]
            or s_max[2] > c_max[2]
        )
        if outside:
            low_excess = (
                max(c_min[0] - s_min[0], 0.0),
                max(c_min[1] - s_min[1], 0.0),
                max(c_min[2] - s_min[2], 0.0),
            )
            high_excess = (
                max(s_max[0] - c_max[0], 0.0),
                max(s_max[1] - c_max[1], 0.0),
                max(s_max[2] - c_max[2], 0.0),
            )
            excess = (
                low_excess[0] + high_excess[0],
                low_excess[1] + high_excess[1],
                low_excess[2] + high_excess[2],
            )
            reports.append(CollisionReport(a=body.name, b="chamber", overlap_xyz=excess))

    return reports
