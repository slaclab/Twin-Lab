"""Tests for the two corrections applied to a pair flagged against its convex hulls."""

from __future__ import annotations

import numpy as np
import pytest

from twin_lab.clearance_refine import (
    MAX_TRIANGLES,
    Refinement,
    _hull_index,
    _segment_distance,
    mesh_separation_m,
    triangles_near,
)

from .test_hull_audit import CUBE_FACES, CUBE_VERTICES, _box


def _refinement(**overrides):
    fields = {
        "parts": ("P001", "P002"),
        "hull_distance_m": -0.001,
        "bulge_m": None,
        "mesh_distance_m": None,
    }
    fields.update(overrides)
    return Refinement(**fields)


def test_separated_boxes_report_the_gap_between_their_faces():
    gap = mesh_separation_m(
        _box([0, 0, 0], [1, 1, 1]),
        CUBE_FACES,
        _box([1.5, 0, 0], [2.5, 1, 1]),
        CUBE_FACES,
    )
    assert gap == pytest.approx(0.5)


def test_boxes_offset_on_every_axis_report_the_corner_to_corner_distance():
    gap = mesh_separation_m(
        _box([0, 0, 0], [1, 1, 1]),
        CUBE_FACES,
        _box([2, 2, 2], [3, 3, 3]),
        CUBE_FACES,
    )
    assert gap == pytest.approx(np.sqrt(3.0))


def test_touching_faces_report_zero_without_being_called_an_intersection():
    gap = mesh_separation_m(
        _box([0, 0, 0], [1, 1, 1]),
        CUBE_FACES,
        _box([1, 0, 0], [2, 1, 1]),
        CUBE_FACES,
    )
    assert gap == pytest.approx(0.0, abs=1e-12)


def test_overlapping_boxes_report_zero():
    gap = mesh_separation_m(
        _box([0, 0, 0], [1, 1, 1]),
        CUBE_FACES,
        _box([0.5, 0.5, 0.5], [1.5, 1.5, 1.5]),
        CUBE_FACES,
    )
    assert gap == 0.0


def test_a_box_swallowed_whole_reports_zero_though_no_edge_crosses_a_face():
    # The candidate-feature minimum alone would return the wall thickness here, which is
    # a positive distance for a pair that is unambiguously in contact.
    gap = mesh_separation_m(
        _box([0, 0, 0], [10, 10, 10]),
        CUBE_FACES,
        _box([4, 4, 4], [6, 6, 6]),
        CUBE_FACES,
    )
    assert gap == pytest.approx(4.0)


def test_an_empty_mesh_cannot_constrain_the_distance():
    assert mesh_separation_m(CUBE_VERTICES, CUBE_FACES[:0], CUBE_VERTICES, CUBE_FACES) == float(
        "inf"
    )


def test_triangles_near_keeps_only_faces_reaching_the_radius():
    vertices = np.concatenate([_box([0, 0, 0], [1, 1, 1]), _box([9, 9, 9], [10, 10, 10])])
    faces = np.concatenate([CUBE_FACES, CUBE_FACES + 8])
    near = triangles_near(vertices, faces, np.array([0.5, 0.5, 0.5]), 1.0)
    assert len(near) == len(CUBE_FACES)
    assert near.max() < 8


def test_triangles_near_truncates_to_the_nearest_when_the_neighbourhood_is_crowded():
    count = MAX_TRIANGLES + 50
    vertices = np.concatenate([_box([i * 1e-4, 0, 0], [1, 1, 1]) for i in range(count)])
    faces = np.concatenate([CUBE_FACES + 8 * i for i in range(count)])
    near = triangles_near(vertices, faces, np.array([0.0, 0.0, 0.0]), 1.0)
    assert len(near) == MAX_TRIANGLES


def test_segment_distance_measures_across_skew_lines():
    a_start = np.array([[-1.0, 0.0, 0.0]])
    a_end = np.array([[1.0, 0.0, 0.0]])
    b_start = np.array([[0.0, -1.0, 2.0]])
    b_end = np.array([[0.0, 1.0, 2.0]])
    assert _segment_distance(a_start, a_end, b_start, b_end) == pytest.approx(2.0)


def test_segment_distance_clamps_to_the_ends_of_parallel_segments():
    a_start = np.array([[0.0, 0.0, 0.0]])
    a_end = np.array([[1.0, 0.0, 0.0]])
    b_start = np.array([[3.0, 0.0, 0.0]])
    b_end = np.array([[4.0, 0.0, 0.0]])
    assert _segment_distance(a_start, a_end, b_start, b_end) == pytest.approx(2.0)


def test_hull_index_reads_the_trailing_number_of_a_compiled_geometry_name():
    # Copied verbatim from a Drake report on the compiled 43841 package: sdf_compiler
    # appends "_collision" after the hull index, so an end-anchored pattern finds nothing.
    assert (
        _hull_index(
            "dsg_000040389_43841_stage_stack::assembly_base::dsg_000040389_43841_stage_stack"
            "::environment_p1170_shield_cone_4_p1170_031_collision"
        )
        == 31
    )
    assert _hull_index("north_crystal_1_p1170_004_collision") == 4
    assert _hull_index("p827_000") == 0
    assert _hull_index("north_crystal_1") is None


def test_mesh_evidence_outranks_the_bulge_correction():
    refinement = _refinement(bulge_m=0.005, mesh_distance_m=-0.0)
    assert refinement.evidence == "mesh"
    assert refinement.verdict == "contact"


def test_clear_cad_underneath_explains_a_hull_contact():
    refinement = _refinement(mesh_distance_m=0.0004)
    assert refinement.verdict == "explained"
    assert "explained by hull proudness" in refinement.describe()


def test_proudness_larger_than_the_overlap_explains_it():
    refinement = _refinement(hull_distance_m=-0.0008, bulge_m=0.0014)
    assert refinement.corrected_m == pytest.approx(0.0006)
    assert refinement.evidence == "bulge"
    assert refinement.verdict == "explained"


def test_proudness_too_small_to_account_for_the_overlap_leaves_it_a_contact():
    refinement = _refinement(hull_distance_m=-0.0030, bulge_m=0.0004)
    assert refinement.verdict == "contact"
    assert "CONTACT" in refinement.describe()


def test_a_pair_with_nothing_cached_behind_it_is_not_judged():
    refinement = _refinement()
    assert refinement.corrected_m is None
    assert refinement.evidence == "none"
    assert refinement.verdict == "unverified"
    assert "unverified" in refinement.describe()
