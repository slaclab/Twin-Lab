"""Ground truth for the clearance measurement, from shapes whose answer is known.

The pipeline's own re-check and the oracle in :mod:`twin_lab.accuracy` share one distance
routine, so a bug in it would agree with itself. These cases come from geometry instead:
planar faces tessellate exactly, so a box pair has an analytic separation, and a sphere
pair has a known sign of error because chords always fall inside the surface they cut.
"""

from __future__ import annotations

import numpy as np
import pytest

from twin_lab.accuracy import WorldMesh, separation_m, triangles_in_box
from twin_lab.clearance_refine import mesh_separation_m


def box(center, half, rotation=None):
    """A closed axis-aligned box, optionally rotated about its own centre."""

    signs = np.array(
        [(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)], dtype=float
    )
    vertices = signs * np.asarray(half, dtype=float)
    if rotation is not None:
        vertices = vertices @ np.asarray(rotation, dtype=float).T
    vertices = vertices + np.asarray(center, dtype=float)
    faces = np.array(
        [
            [0, 1, 3], [0, 3, 2],  # x = -1
            [4, 7, 5], [4, 6, 7],  # x = +1
            [0, 4, 5], [0, 5, 1],  # y = -1
            [2, 3, 7], [2, 7, 6],  # y = +1
            [0, 2, 6], [0, 6, 4],  # z = -1
            [1, 5, 7], [1, 7, 3],  # z = +1
        ],
        dtype=np.int32,
    )
    return vertices, faces


def sphere(center, radius, segments=32):
    """A UV sphere whose facets are inscribed, so every point lies on or inside the ball."""

    theta = np.linspace(0.0, np.pi, segments // 2 + 1)
    phi = np.linspace(0.0, 2.0 * np.pi, segments, endpoint=False)
    grid_theta, grid_phi = np.meshgrid(theta, phi, indexing="ij")
    points = np.stack(
        [
            np.sin(grid_theta) * np.cos(grid_phi),
            np.sin(grid_theta) * np.sin(grid_phi),
            np.cos(grid_theta) * np.ones_like(grid_phi),
        ],
        axis=-1,
    ).reshape(-1, 3)
    vertices = points * radius + np.asarray(center, dtype=float)
    rows, columns = len(theta), len(phi)
    faces = []
    for row in range(rows - 1):
        for column in range(columns):
            a = row * columns + column
            b = row * columns + (column + 1) % columns
            faces.append([a, b, a + columns])
            faces.append([b, b + columns, a + columns])
    return vertices, np.array(faces, dtype=np.int32)


def rotation_z(angle):
    cos, sin = np.cos(angle), np.sin(angle)
    return np.array([[cos, -sin, 0.0], [sin, cos, 0.0], [0.0, 0.0, 1.0]])


@pytest.mark.parametrize("gap", [0.05, 0.005, 0.0005])
def test_face_to_face_separation_is_exact(gap):
    a = box((0.0, 0.0, 0.0), (0.1, 0.1, 0.1))
    b = box((0.2 + gap, 0.0, 0.0), (0.1, 0.1, 0.1))
    assert mesh_separation_m(*a, *b) == pytest.approx(gap, abs=1e-12)


def test_vertex_to_face_separation_is_exact():
    corner = box((0.0, 0.0, 0.0), (0.05, 0.05, 0.05), rotation_z(np.pi / 4))
    wall = box((0.15, 0.0, 0.0), (0.05, 0.2, 0.2))
    # The rotated cube presents a vertical edge at x = 0.05 * sqrt(2).
    assert mesh_separation_m(*corner, *wall) == pytest.approx(0.1 - 0.05 * np.sqrt(2.0), abs=1e-12)


def test_edge_to_edge_separation_is_exact():
    lower = box((0.0, 0.0, 0.0), (0.2, 0.005, 0.005))
    upper = box((0.0, 0.0, 0.02), (0.005, 0.2, 0.005), rotation_z(np.pi / 4))
    assert mesh_separation_m(*lower, *upper) == pytest.approx(0.01, abs=1e-12)


def test_overlap_reports_zero():
    a = box((0.0, 0.0, 0.0), (0.1, 0.1, 0.1))
    b = box((0.15, 0.0, 0.0), (0.1, 0.1, 0.1))
    assert mesh_separation_m(*a, *b) == 0.0


def test_tessellation_only_ever_overstates_the_gap():
    """Curved surfaces read as further apart than they are, never closer.

    This is the whole reason the report is safe to act on: the residual error left after
    the CAD re-check is one-sided, so a pair the tool calls clear by more than that error
    really is clear.
    """

    radius, segments = 0.05, 24
    for gap in (0.02, 0.002, 0.0002):
        a = sphere((0.0, 0.0, 0.0), radius, segments)
        b = sphere((2.0 * radius + gap, 0.0, 0.0), radius, segments)
        measured = mesh_separation_m(*a, *b)
        sagitta = radius * (1.0 - np.cos(np.pi / segments))
        assert measured >= gap
        assert measured <= gap + 2.0 * sagitta + 1e-12


def test_triangles_in_box_keeps_every_face_that_reaches_it():
    vertices, faces = box((0.0, 0.0, 0.0), (0.1, 0.1, 0.1))
    lower = np.array([0.099, -1.0, -1.0])
    upper = np.array([1.0, 1.0, 1.0])
    kept = triangles_in_box(vertices, faces, lower, upper)
    # Only the two faces lying wholly at x = -0.1 fall outside the slab.
    assert len(kept) == len(faces) - 2
    assert mesh_separation_m(vertices, kept, *box((0.3, 0.0, 0.0), (0.1, 0.1, 0.1))) == (
        pytest.approx(0.1, abs=1e-12)
    )


def placed(mesh):
    return WorldMesh.place(mesh, np.eye(4))


@pytest.mark.parametrize("gap", [0.05, 0.004, 0.0])
def test_box_splitting_agrees_with_the_direct_answer(gap):
    """The split search is only worth trusting if it returns what brute force would.

    A budget of one forces a split at every level, so this exercises the recursion rather
    than the leaf it usually falls straight through to.
    """

    a = box((0.0, 0.0, 0.0), (0.2, 0.05, 0.05))
    b = box((0.4 + gap, 0.0, 0.0), (0.2, 0.05, 0.05))
    expected = min(gap, 0.005)
    assert separation_m(placed(a), placed(b), warn_m=0.005, budget=1) == pytest.approx(
        expected, abs=1e-12
    )


def test_box_splitting_reports_the_band_for_distant_parts():
    a = box((0.0, 0.0, 0.0), (0.05, 0.05, 0.05))
    b = box((1.0, 0.0, 0.0), (0.05, 0.05, 0.05))
    assert separation_m(placed(a), placed(b), warn_m=0.005) == 0.005


def test_box_splitting_finds_a_contact_hidden_in_a_large_shared_volume():
    """Interleaved parts share almost all of their bounds, which is the case that has to split.

    The two frames occupy the same metre of space and touch nowhere except one 2 mm island,
    so a search that gave up on the shared bounding box would report them clear.
    """

    rails = [
        box((0.0, y, 0.0), (0.5, 0.002, 0.002))
        for y in np.linspace(-0.4, 0.4, 9)
    ]
    posts = [
        box((x, 0.0, 0.02), (0.002, 0.5, 0.002))
        for x in np.linspace(-0.4, 0.4, 9)
    ]
    touching = box((0.1, 0.1, 0.0), (0.002, 0.002, 0.002))
    frame = _merge([*rails, touching])
    other = _merge(posts + [box((0.1, 0.1, 0.006), (0.002, 0.002, 0.002))])
    assert separation_m(placed(frame), placed(other), warn_m=0.005, budget=64) == (
        pytest.approx(0.002, abs=1e-12)
    )


def _merge(meshes):
    vertices, faces, offset = [], [], 0
    for mesh_vertices, mesh_faces in meshes:
        vertices.append(mesh_vertices)
        faces.append(mesh_faces + offset)
        offset += len(mesh_vertices)
    return np.concatenate(vertices), np.concatenate(faces)
