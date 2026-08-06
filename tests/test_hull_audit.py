"""Tests for the hull accuracy metrics: volume, bulge, and uncovered material."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from twin_lab.hull_audit import (
    BULGE_RAMP_RGB,
    BULGE_RAMP_STOPS,
    MM_PER_M,
    PartAudit,
    PartFit,
    _audit_key,
    _bulge_colors,
    _read_audit_cache,
    _write_audit_cache,
    audit_part,
    load_hull,
    mesh_volume,
    outside_distance,
    part_fit,
    surface_distance,
    tour_labels,
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


def test_part_fit_keeps_one_bulge_per_hull_vertex_in_hull_order(tmp_path):
    """The overview slices this array per hull, so its order and length are load bearing."""

    spanning = load_hull(_write_obj(tmp_path / "a.obj", _box([0, 0, 0], [2, 2, 1]), CUBE_FACES))
    exact = load_hull(_write_obj(tmp_path / "b.obj", _box([0, 0, 0], [2, 1, 1]), CUBE_FACES))
    vertices = np.concatenate([_box([0, 0, 0], [2, 1, 1]), _box([0, 1, 0], [1, 2, 1])])
    faces = np.concatenate([CUBE_FACES, CUBE_FACES + 8])
    fit = part_fit(vertices, faces, [spanning, exact])
    assert len(fit.bulge_m) == len(spanning.vertices) + len(exact.vertices)
    assert len(fit.gap_m) == len(vertices)
    assert fit.bulge_m[: len(spanning.vertices)].max() == pytest.approx(1.0)
    assert fit.bulge_m[len(spanning.vertices) :].max() == pytest.approx(0.0)


def test_bulge_colors_span_the_ramp_and_saturate_beyond_the_scale():
    scale_mm = 2.0
    stops = np.array(BULGE_RAMP_STOPS) * scale_mm
    bulge = np.concatenate([[0.0], stops, [scale_mm * 10.0]]) / MM_PER_M
    colors = _bulge_colors(bulge, scale_mm)
    assert colors[0] == pytest.approx(BULGE_RAMP_RGB[0])
    assert colors[1] == pytest.approx(BULGE_RAMP_RGB[0])
    assert colors[2] == pytest.approx(BULGE_RAMP_RGB[1])
    assert colors[3] == pytest.approx(BULGE_RAMP_RGB[2])
    assert colors[4] == pytest.approx(BULGE_RAMP_RGB[2])


def test_bulge_under_the_noise_floor_stays_the_colour_of_a_clean_hull():
    """A ramp starting at zero paints every hull amber; the median vertex bulges 0.17 mm."""

    below = _bulge_colors(np.array([0.00017]), 2.0)
    assert below[0] == pytest.approx(BULGE_RAMP_RGB[0])


def _audit(part_ref: str) -> PartAudit:
    return PartAudit(
        source=Path("a003.obj"),
        part_ref=part_ref,
        triangles=12,
        hull_count=2,
        mesh_volume_m3=1.0,
        hull_volume_m3=1.25,
        max_bulge_mm=2.5,
        mean_bulge_mm=0.5,
        max_gap_mm=0.125,
        outside_fraction=0.25,
    )


def test_cached_measurements_survive_the_round_trip(tmp_path):
    path = tmp_path / "audit.npz"
    fit = PartFit(bulge_m=np.array([0.0, 0.0025]), gap_m=np.array([0.000125, 0.0, 0.0]))
    _write_audit_cache(path, "key", {"P013": (_audit("P013"), fit)})
    restored = _read_audit_cache(path, "key", Path("a003.obj"))
    audit, restored_fit = restored["P013"]
    assert audit == _audit("P013")
    assert restored_fit.bulge_m == pytest.approx(fit.bulge_m)
    assert restored_fit.gap_m == pytest.approx(fit.gap_m)


def test_cache_is_discarded_when_its_inputs_moved(tmp_path):
    """Silently reporting last week's hulls would be worse than spending the seconds again."""

    path = tmp_path / "audit.npz"
    fit = PartFit(bulge_m=np.zeros(1), gap_m=np.zeros(1))
    _write_audit_cache(path, "key", {"P013": (_audit("P013"), fit)})
    assert _read_audit_cache(path, "other key", Path("a003.obj")) == {}
    path.write_bytes(b"not an npz")
    assert _read_audit_cache(path, "key", Path("a003.obj")) == {}
    assert _read_audit_cache(tmp_path / "absent.npz", "key", Path("a003.obj")) == {}


def test_audit_key_tracks_the_mesh_the_hulls_and_the_seed():
    manifest = {"source_sha256": "aa", "source_size": 10, "parts_settings_sig": "sig"}
    base = _audit_key(manifest, 0)
    assert _audit_key(dict(manifest), 0) == base
    assert _audit_key({**manifest, "source_sha256": "bb"}, 0) != base
    assert _audit_key({**manifest, "parts_settings_sig": "other"}, 0) != base
    assert _audit_key(manifest, 1) != base


def test_tour_labels_count_from_one_and_carry_every_metric():
    labels = tour_labels(0, 10, _audit("P013"))
    assert labels[0] == "Part 1 of 10: a003/P013"
    assert "1.25x" in labels[1] and "2 hulls" in labels[1]
    assert "2.50 mm" in labels[2]
    assert "0.125 mm" in labels[3]


def test_tour_labels_stay_usable_as_meshcat_control_names():
    """Drake pastes a control name into a single-quoted JS literal, so a quote drops it."""

    labels = tour_labels(3, 10, _audit("P013"))
    assert not any("'" in label for label in labels)
    assert len(set(labels)) == len(labels)
