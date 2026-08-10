"""The inflation pass has one job: make a hull contain the part it replaces."""

from __future__ import annotations

import numpy as np
import pytest

from twin_lab.hull_audit import Hull, load_hull, outside_distance, surface_gap
from twin_lab.hull_inflation import convex_hull, hull_margins, inflate

CUBE_FACES = np.array(
    [
        [0, 1, 3], [0, 3, 2], [4, 7, 5], [4, 6, 7],
        [0, 4, 5], [0, 5, 1], [2, 3, 7], [2, 7, 6],
        [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3],
    ],
    dtype=np.int32,
)


def cube(lower: float = 0.0, upper: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    corners = [(x, y, z) for x in (lower, upper) for y in (lower, upper) for z in (lower, upper)]
    return np.array(corners, dtype=np.float64), CUBE_FACES


def as_hull(vertices: np.ndarray, faces: np.ndarray, tmp_path) -> Hull:
    path = tmp_path / f"hull{abs(hash(vertices.tobytes())) % 100000}.obj"
    rows = [f"v {x:.12g} {y:.12g} {z:.12g}" for x, y, z in vertices]
    rows += [f"f {a + 1} {b + 1} {c + 1}" for a, b, c in faces]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return load_hull(path)


def test_the_hull_of_a_convex_body_is_the_body_itself():
    vertices, faces = cube()
    interior = np.append(vertices, [[0.5, 0.5, 0.5]], axis=0)
    points, triangles = convex_hull(interior, faces)
    assert len(points) == 8
    assert sorted(map(tuple, np.round(points, 9))) == sorted(map(tuple, np.round(vertices, 9)))
    assert len(triangles) == 12


@pytest.mark.parametrize("margin", [0.05, 0.005, 0.0005])
def test_inflation_grows_the_body_by_exactly_the_margin(margin):
    vertices, faces = cube()
    grown, _ = inflate(vertices, faces, margin)
    assert grown.min(axis=0) == pytest.approx(np.full(3, -margin))
    assert grown.max(axis=0) == pytest.approx(np.full(3, 1.0 + margin))


def test_inflation_is_a_superset_in_every_direction(tmp_path):
    """A cube is the loosest case for a ball: the diagonal is where growth is thinnest."""

    vertices, faces = cube()
    margin = 0.01
    grown, grown_faces = inflate(vertices, faces, margin)
    hull = as_hull(grown, grown_faces, tmp_path)
    rng = np.random.default_rng(0)
    direction = rng.normal(size=(2000, 3))
    direction /= np.linalg.norm(direction, axis=1)[:, None]
    # Every point within the margin of an original corner must now be inside.
    probes = vertices[rng.integers(0, 8, len(direction))] + direction * margin
    assert outside_distance([hull], probes).max() == 0.0


def test_a_zero_margin_leaves_the_hull_untouched():
    vertices, faces = cube()
    grown, grown_faces = inflate(vertices, faces, 0.0)
    assert grown is vertices
    assert grown_faces is faces


def test_the_exact_gap_exceeds_the_plane_gap_at_a_corner(tmp_path):
    """Plane distance is what the audit reports and it understates the truth off a corner."""

    hull = as_hull(*cube(), tmp_path)
    probe = np.array([[1.1, 1.1, 1.1]])
    plane = outside_distance([hull], probe)[0]
    exact, nearest = surface_gap([hull], probe)
    assert plane == pytest.approx(0.1)
    assert exact[0] == pytest.approx(np.sqrt(3) * 0.1)
    assert nearest[0] == 0


def test_points_inside_a_hull_report_no_gap(tmp_path):
    hull = as_hull(*cube(), tmp_path)
    exact, nearest = surface_gap([hull], np.array([[0.5, 0.5, 0.5], [0.1, 0.9, 0.2]]))
    assert exact.tolist() == [0.0, 0.0]
    assert nearest.tolist() == [-1, -1]


def test_only_the_hull_nearest_an_uncovered_vertex_has_to_grow(tmp_path):
    """A part that misfits at one end must not gain material at the other."""

    left = as_hull(*cube(0.0, 1.0), tmp_path)
    right = as_hull(*cube(2.0, 3.0), tmp_path)
    mesh = np.array([[0.5, 0.5, 0.5], [2.5, 2.5, 2.5], [3.2, 2.5, 2.5]])
    margins = hull_margins([left, right], mesh)
    assert margins[0] == 0.0
    assert margins[1] == pytest.approx(0.2)


def test_growing_by_the_measured_margin_covers_the_part(tmp_path):
    """The whole point of the pass, end to end, on a hull that starts out too small."""

    vertices, faces = cube(0.05, 0.95)
    hull = as_hull(vertices, faces, tmp_path)
    mesh = cube()[0]
    assert outside_distance([hull], mesh).max() > 0.0

    margin = hull_margins([hull], mesh)[0]
    grown = as_hull(*inflate(hull.vertices, hull.faces, float(margin)), tmp_path)
    assert outside_distance([grown], mesh).max() == 0.0
