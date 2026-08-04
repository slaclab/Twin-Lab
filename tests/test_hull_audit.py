"""Tests for the hull accuracy metrics: volume, bulge, and uncovered material."""

from __future__ import annotations

import numpy as np
import pytest

from twin_lab.hull_audit import (
    audit_part,
    load_hull,
    mesh_volume,
    outside_distance,
    surface_distance,
    union_volume,
)

CUBE_VERTICES = np.array(
    [
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [1.0, 1.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
        [1.0, 0.0, 1.0],
        [1.0, 1.0, 1.0],
        [0.0, 1.0, 1.0],
    ]
)
CUBE_FACES = np.array(
    [
        [0, 2, 1],
        [0, 3, 2],
        [4, 5, 6],
        [4, 6, 7],
        [0, 1, 5],
        [0, 5, 4],
        [1, 2, 6],
        [1, 6, 5],
        [2, 3, 7],
        [2, 7, 6],
        [3, 0, 4],
        [3, 4, 7],
    ],
    dtype=np.int32,
)


def _write_obj(path, vertices, faces):
    lines = [f"v {x:.9g} {y:.9g} {z:.9g}" for x, y, z in vertices]
    lines += [f"f {a + 1} {b + 1} {c + 1}" for a, b, c in faces]
    path.write_text("\n".join(lines) + "\n", encoding="ascii")
    return path


def _box(lower, upper):
    lower = np.asarray(lower, dtype=float)
    upper = np.asarray(upper, dtype=float)
    return CUBE_VERTICES * (upper - lower) + lower


def test_mesh_volume_is_exact_for_a_closed_box():
    assert mesh_volume(_box([0, 0, 0], [2, 3, 4]), CUBE_FACES) == pytest.approx(24.0)


def test_mesh_volume_ignores_where_the_part_sits():
    """A cracked tessellation leaks a term that grows with distance from the reference."""

    cracked = CUBE_FACES[:-1]
    near = mesh_volume(_box([0, 0, 0], [1, 1, 1]), cracked)
    far = mesh_volume(_box([100, 0, 0], [101, 1, 1]), cracked)
    assert near == pytest.approx(far)


def test_union_volume_discounts_overlap(tmp_path):
    first = load_hull(_write_obj(tmp_path / "a.obj", _box([0, 0, 0], [1, 1, 1]), CUBE_FACES))
    second = load_hull(_write_obj(tmp_path / "b.obj", _box([0.5, 0, 0], [1.5, 1, 1]), CUBE_FACES))
    rng = np.random.default_rng(0)
    assert union_volume([first], rng) == pytest.approx(1.0)
    # Two unit boxes overlapping by half: 1.5, not the 2.0 a naive sum would report.
    assert union_volume([first, second], rng) == pytest.approx(1.5, abs=0.05)


def test_outside_distance_is_zero_inside_and_positive_outside(tmp_path):
    hull = load_hull(_write_obj(tmp_path / "a.obj", CUBE_VERTICES, CUBE_FACES))
    points = np.array([[0.5, 0.5, 0.5], [0.0, 0.0, 0.0], [0.5, 0.5, 1.25]])
    assert outside_distance([hull], points) == pytest.approx([0.0, 0.0, 0.25])


def test_surface_distance_is_negative_inside_the_part():
    points = np.array([[0.5, 0.5, 2.0], [2.0, 0.5, 0.5], [0.5, 0.5, 0.5]])
    distances = surface_distance(points, CUBE_VERTICES, CUBE_FACES)
    assert distances == pytest.approx([1.0, 1.0, -0.5])


def test_bulge_ignores_hull_vertices_buried_inside_the_part(tmp_path):
    """A hull that fills a solid region adds nothing, however deep its vertices sit.

    Unsigned distance made static_A003/P024 report 4.42 mm of bulge on a part whose
    hulls fit it to 8% by volume; the offending vertex was 4.42 mm inside the solid.
    """

    inner = load_hull(
        _write_obj(tmp_path / "a.obj", _box([0.25, 0.25, 0.25], [0.75, 0.75, 0.75]), CUBE_FACES)
    )
    audit = audit_part(
        tmp_path / "src.obj",
        "P001",
        CUBE_VERTICES,
        CUBE_FACES,
        [inner],
        np.random.default_rng(0),
    )
    assert audit.max_bulge_mm == pytest.approx(0.0)
    assert audit.mean_bulge_mm == pytest.approx(0.0)


def test_audit_reports_a_perfect_fit_for_a_convex_part(tmp_path):
    hull = load_hull(_write_obj(tmp_path / "a.obj", CUBE_VERTICES, CUBE_FACES))
    audit = audit_part(
        tmp_path / "src.obj",
        "P001",
        CUBE_VERTICES,
        CUBE_FACES,
        [hull],
        np.random.default_rng(0),
    )
    assert audit.volume_ratio == pytest.approx(1.0)
    assert audit.max_bulge_mm == pytest.approx(0.0)
    assert audit.max_gap_mm == pytest.approx(0.0)
    assert audit.outside_fraction == 0.0


def test_audit_measures_the_concavity_a_single_hull_spans(tmp_path):
    # An L: the convex hull of it fills the notch, so the ratio must exceed one.
    vertices = np.concatenate([_box([0, 0, 0], [2, 1, 1]), _box([0, 1, 0], [1, 2, 1])])
    faces = np.concatenate([CUBE_FACES, CUBE_FACES + 8])
    hull = load_hull(_write_obj(tmp_path / "a.obj", _box([0, 0, 0], [2, 2, 1]), CUBE_FACES))
    audit = audit_part(
        tmp_path / "src.obj", "P001", vertices, faces, [hull], np.random.default_rng(0)
    )
    assert audit.mesh_volume_m3 == pytest.approx(3.0)
    assert audit.volume_ratio == pytest.approx(4.0 / 3.0)
    assert audit.max_gap_mm == pytest.approx(0.0)
    assert audit.max_bulge_mm == pytest.approx(1000.0)
