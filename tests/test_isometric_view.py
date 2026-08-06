from __future__ import annotations

import numpy as np
import pytest

from twin_lab.collision_viewer import ISOMETRIC_DISTANCE, isometric_camera


def _standoff(lower, upper) -> float:
    camera, target = isometric_camera(lower, upper)
    return float(np.linalg.norm(camera - target))


def test_the_camera_looks_at_the_centre_of_the_assembly():
    _, target = isometric_camera(np.array([0.0, -2.0, 1.0]), np.array([4.0, 2.0, 3.0]))

    assert target == pytest.approx([2.0, 0.0, 2.0])


def test_the_camera_sits_at_equal_angles_to_all_three_axes():
    """That equality is the whole definition of an isometric view."""
    camera, target = isometric_camera(np.array([-1.0, -1.0, -1.0]), np.array([1.0, 1.0, 1.0]))

    offset = np.abs(camera - target)
    assert offset[0] == pytest.approx(offset[1])
    assert offset[1] == pytest.approx(offset[2])


def test_the_camera_stands_at_the_near_left_corner():
    """Pinned by eye against the CAD package's isometric, so the two views agree."""
    camera, target = isometric_camera(np.array([-1.0, -1.0, -1.0]), np.array([1.0, 1.0, 1.0]))

    offset = camera - target
    assert offset[2] > 0, "looking down on the stack, not up at it"
    assert offset[0] > 0, "+X -Y is the near left corner"
    assert offset[1] < 0


def test_the_camera_stands_back_far_enough_to_frame_the_whole_box():
    lower, upper = np.zeros(3), np.ones(3)
    radius = float(np.linalg.norm(upper - lower)) / 2.0

    assert _standoff(lower, upper) == pytest.approx(radius * ISOMETRIC_DISTANCE)
    # 1.64 R is where a sphere of radius R just fills Drake's 75 degree field of view.
    assert ISOMETRIC_DISTANCE > 1.64


def test_a_bigger_assembly_pushes_the_camera_further_out():
    assert _standoff(np.zeros(3), np.full(3, 10.0)) > _standoff(np.zeros(3), np.ones(3))


def test_a_flat_assembly_does_not_put_the_camera_on_top_of_it():
    """A zero-size box would otherwise place the camera exactly at its own target."""
    assert _standoff(np.zeros(3), np.zeros(3)) > 0.0
