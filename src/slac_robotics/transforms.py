"""Rigid transform helpers for stage kinematics."""

from __future__ import annotations

import math
from typing import List, Tuple

Mat4 = List[List[float]]
Vec3 = Tuple[float, float, float]


def normalize(axis: Vec3) -> Vec3:
    norm = math.sqrt(axis[0] * axis[0] + axis[1] * axis[1] + axis[2] * axis[2])
    if norm == 0.0:
        raise ValueError("Axis vector must be non-zero")
    return (axis[0] / norm, axis[1] / norm, axis[2] / norm)


def make_transform(rotation: List[List[float]], translation: Vec3) -> Mat4:
    tf: Mat4 = [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
    for r in range(3):
        for c in range(3):
            tf[r][c] = float(rotation[r][c])
    tf[0][3], tf[1][3], tf[2][3] = translation
    return tf


def matmul(a: Mat4, b: Mat4) -> Mat4:
    out: Mat4 = [[0.0] * 4 for _ in range(4)]
    for r in range(4):
        for c in range(4):
            out[r][c] = (
                a[r][0] * b[0][c] + a[r][1] * b[1][c] + a[r][2] * b[2][c] + a[r][3] * b[3][c]
            )
    return out


def transform_point(tf: Mat4, point: Vec3) -> Vec3:
    x, y, z = point
    tx = tf[0][0] * x + tf[0][1] * y + tf[0][2] * z + tf[0][3]
    ty = tf[1][0] * x + tf[1][1] * y + tf[1][2] * z + tf[1][3]
    tz = tf[2][0] * x + tf[2][1] * y + tf[2][2] * z + tf[2][3]
    return (tx, ty, tz)


def translate(offset: Vec3) -> Mat4:
    return make_transform(
        [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ],
        offset,
    )


def rotate_about_axis(axis: Vec3, radians: float) -> Mat4:
    """Rodrigues rotation matrix about an arbitrary axis."""
    x, y, z = normalize(axis)
    c = math.cos(radians)
    s = math.sin(radians)
    one_c = 1.0 - c

    rot = [
        [c + x * x * one_c, x * y * one_c - z * s, x * z * one_c + y * s],
        [y * x * one_c + z * s, c + y * y * one_c, y * z * one_c - x * s],
        [z * x * one_c - y * s, z * y * one_c + x * s, c + z * z * one_c],
    ]
    return make_transform(rot, (0.0, 0.0, 0.0))


def move_along_axis(axis: Vec3, distance: float) -> Mat4:
    direction = normalize(axis)
    return translate((direction[0] * distance, direction[1] * distance, direction[2] * distance))


def gonio_motion(axis: Vec3, radians: float) -> Mat4:
    """For now, model gonio as a single-axis angular stage."""
    return rotate_about_axis(axis, radians)
