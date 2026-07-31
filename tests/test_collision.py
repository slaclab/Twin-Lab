"""Tests for convex decomposition caching, clearance reporting, and viewer sliders."""

from __future__ import annotations

import json
import math
import os

import pytest

from twin_lab.collision import (
    Clearance,
    ClearanceReport,
    _pair_key,
    _part_of,
    _short,
    read_ignored_pairs,
)
from twin_lab.collision_viewer import SliderJoint, read_joint_metadata
from twin_lab.convex_collision import (
    CACHE_SCHEMA,
    ConvexPart,
    DecompositionSettings,
    _clear_part_dir,
    _read_manifest,
    _read_part_marker,
    _write_manifest,
    _write_part_marker,
    read_obj_parts,
)

SPLIT_OBJ = """\
o P001
v 0 0 0
v 1 0 0
v 0 1 0
f 1 2 3
o P002
v 0 0 5
v 1 0 5
v 0 1 5
f 4 5 6
"""


def test_read_obj_parts_splits_on_group_markers_and_rebases_indices(tmp_path):
    path = tmp_path / "merged.obj"
    path.write_text(SPLIT_OBJ, encoding="utf-8")

    parts = read_obj_parts(path)

    assert [ref for ref, _, _ in parts] == ["P001", "P002"]
    assert parts[1][1] == [(0.0, 0.0, 5.0), (1.0, 0.0, 5.0), (0.0, 1.0, 5.0)]
    # The second face used global indices 4-6; after splitting it must be local 0-2.
    assert parts[1][2] == [(0, 1, 2)]


def test_read_obj_parts_falls_back_to_the_file_stem_without_group_markers(tmp_path):
    path = tmp_path / "kohzu_sa04b.obj"
    path.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8")

    parts = read_obj_parts(path)

    assert [ref for ref, _, _ in parts] == ["kohzu_sa04b"]
    assert parts[0][2] == [(0, 1, 2)]


def test_decomposition_settings_round_trip_through_the_cache_key():
    settings = DecompositionSettings(threshold=0.02, max_hulls=16, seed=7)

    assert settings.as_dict() == {"threshold": 0.02, "max_hulls": 16, "seed": 7}
    # The manifest must be JSON-serialisable so cache validation can compare it verbatim.
    assert json.loads(json.dumps(settings.as_dict())) == settings.as_dict()
    assert CACHE_SCHEMA.startswith("slac-convex-decomposition/")


@pytest.mark.parametrize(
    ("geometry_name", "expected"),
    [
        ("stack::link::stack::a043_moving_1_collision", "A043"),
        ("stack::link::stack::environment_a037_enclosure_assembly_1_collision", "A037"),
        ("stack::link::stack::p901_hull003_collision", "P901"),
        ("stack::link::stack::kohzu_sa04b_collision", "kohzu_sa04b_collision"),
    ],
)
def test_part_of_finds_references_that_are_delimited_by_underscores(geometry_name, expected):
    assert _part_of(geometry_name) == expected


def test_short_names_a_geometry_by_its_link_and_part():
    name = "stack::north_crystal_02_a050_motion::stack::a050_moving_1_collision"

    assert _short(name) == "north_crystal_02_a050_motion/A050"


def test_pair_key_is_order_independent():
    assert _pair_key("A050", "A037") == _pair_key("A037", "A050")


def test_clearance_report_splits_touching_from_warnings():
    report = ClearanceReport(
        clearances=(
            Clearance("a::l::a::a001_collision", "a::l::a::a002_collision", -0.002),
            Clearance("a::l::a::a003_collision", "a::l::a::a004_collision", 0.0),
            Clearance("a::l::a::a005_collision", "a::l::a::a006_collision", 0.003),
            Clearance("a::l::a::a007_collision", "a::l::a::a008_collision", 0.009),
        ),
        warn_m=0.005,
    )

    assert [item.distance_m for item in report.touching] == [-0.002, 0.0]
    assert [item.distance_m for item in report.warnings] == [0.003]
    assert report.worst_m == -0.002
    assert "TOUCHING" in report.summary()


def test_empty_clearance_report_reads_as_clear():
    report = ClearanceReport(clearances=(), warn_m=0.005)

    assert report.worst_m is None
    assert report.summary() == "clear: nothing within 5 mm"


def test_geometry_states_paint_contact_red_and_near_misses_yellow():
    shared = "a::l::a::a003_collision"
    report = ClearanceReport(
        clearances=(
            Clearance("a::l::a::a001_collision", "a::l::a::a002_collision", -0.002),
            Clearance(shared, "a::l::a::a004_collision", 0.001),
            # The shared geometry also touches, and contact has to win over the near miss.
            Clearance("a::l::a::a005_collision", shared, -0.001),
            Clearance("a::l::a::a006_collision", "a::l::a::a007_collision", 0.009),
        ),
        warn_m=0.005,
    )

    states = report.geometry_states()

    assert states["a::l::a::a001_collision"] == "interference"
    assert states["a::l::a::a004_collision"] == "close"
    assert states[shared] == "interference"
    # Beyond the warning band nothing is painted, so a clear pose leaves the model alone.
    assert "a::l::a::a006_collision" not in states


def test_read_ignored_pairs_is_order_independent(tmp_path):
    path = tmp_path / "ignore.yaml"
    path.write_text(
        "ignored_pairs:\n"
        "  - pair: [A050, A037]\n"
        "    reason: cable tray passes through the reviewed envelope\n",
        encoding="utf-8",
    )

    pairs = read_ignored_pairs(path)

    assert _pair_key("A037", "A050") in pairs
    assert _pair_key("A050", "A037") in pairs


def test_prismatic_slider_bounds_are_reported_in_millimetres_about_the_logical_home():
    joint = SliderJoint(
        joint_name="detector_a041_motion",
        stack="Detector",
        stage_ref="A041",
        joint_type="prismatic",
        sdf_lower=-0.4,
        sdf_upper=0.0,
        logical_offset=0.0,
        reviewed_home=0.0,
    )

    assert joint.unit == "mm"
    assert joint.slider_bounds() == pytest.approx((-400.0, 0.0, 0.0))
    assert joint.to_sdf(-250.0) == pytest.approx(-0.25)


def test_revolute_slider_bounds_recentre_on_the_reviewed_home_angle():
    # A049 is reviewed in degrees over [150, 210] with a logical home of 180 degrees.
    joint = SliderJoint(
        joint_name="north_crystal_a049_motion",
        stack="North Crystal",
        stage_ref="A049",
        joint_type="revolute",
        sdf_lower=math.radians(-30.0),
        sdf_upper=math.radians(30.0),
        logical_offset=math.pi,
        reviewed_home=math.pi,
    )

    lower, upper, home = joint.slider_bounds()

    assert (lower, upper, home) == pytest.approx((150.0, 210.0, 180.0))
    assert joint.unit == "deg"
    # A slider reading of 180 degrees must sit at the SDF origin, not at pi.
    assert joint.to_sdf(180.0) == pytest.approx(0.0)
    assert joint.to_sdf(210.0) == pytest.approx(math.radians(30.0))


def test_slider_home_follows_the_reviewed_home_not_the_cad_pose():
    # A066/A064/A060 are modelled 3.105 mm off centre, but travel is [-4, +4] mm
    # and the reviewed home is the centre of travel.
    joint = SliderJoint(
        joint_name="north_polycap_a066_z",
        stack="North Polycap",
        stage_ref="A066",
        joint_type="prismatic",
        sdf_lower=-0.000894545,
        sdf_upper=0.007105455,
        logical_offset=-0.003105455,
        reviewed_home=0.0,
    )

    assert joint.slider_bounds() == pytest.approx((-4.0, 4.0, 0.0))
    # Home still has to map back onto the CAD-relative SDF coordinate.
    assert joint.to_sdf(0.0) == pytest.approx(0.003105455)


def test_read_joint_metadata_parses_the_compiled_table(tmp_path):
    (tmp_path / "joint_metadata.csv").write_text(
        "joint_name,stack,stage_ref,type,sdf_lower,sdf_upper,logical_home_offset,"
        "reviewed_home,units,axis_x,axis_y,axis_z\n"
        "detector_a041_motion,Detector,A041,prismatic,-0.4,0.0,0.0,0.0,m,1,0,0\n",
        encoding="utf-8",
    )

    joints = read_joint_metadata(tmp_path)

    assert len(joints) == 1
    assert joints[0].label == "Detector / A041 detector_a041_motion (mm)"
    assert joints[0].slider_bounds() == pytest.approx((-400.0, 0.0, 0.0))


def _marker_fixture(tmp_path):
    """A source mesh plus a part directory holding one finished hull."""

    source = tmp_path / "static_A037.obj"
    source.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nv 0 0 1\nf 1 2 3\n", encoding="utf-8")
    part_dir = tmp_path / "cache" / "static_a037"
    part_dir.mkdir(parents=True)
    hull = part_dir / "p650_hull000.obj"
    hull.write_text("v 0 0 0\n", encoding="utf-8")
    part = ConvexPart(source=source, part_ref="P650", hulls=(hull,))
    return source, part_dir, part


def test_part_marker_round_trips_so_an_interrupted_build_resumes(tmp_path):
    source, part_dir, part = _marker_fixture(tmp_path)
    settings = DecompositionSettings()
    marker = part_dir / "part0005.json"

    _write_part_marker(marker, source, settings, part)
    resumed = _read_part_marker(marker, source, settings)

    assert resumed is not None
    assert resumed.part_ref == "P650"
    assert resumed.hulls == (part_dir / "p650_hull000.obj",)


def test_part_marker_is_rejected_when_settings_change(tmp_path):
    source, part_dir, part = _marker_fixture(tmp_path)
    marker = part_dir / "part0005.json"
    _write_part_marker(marker, source, DecompositionSettings(), part)

    assert _read_part_marker(marker, source, DecompositionSettings(max_hulls=4)) is None


def test_part_marker_is_rejected_when_the_source_mesh_changes(tmp_path):
    source, part_dir, part = _marker_fixture(tmp_path)
    settings = DecompositionSettings()
    marker = part_dir / "part0005.json"
    _write_part_marker(marker, source, settings, part)

    source.write_text("v 0 0 0\nv 2 0 0\nv 0 2 0\nv 0 0 2\nf 1 2 3\n", encoding="utf-8")

    assert _read_part_marker(marker, source, settings) is None


def test_part_marker_is_rejected_when_its_hull_file_is_missing(tmp_path):
    source, part_dir, part = _marker_fixture(tmp_path)
    settings = DecompositionSettings()
    marker = part_dir / "part0005.json"
    _write_part_marker(marker, source, settings, part)
    part.hulls[0].unlink()

    assert _read_part_marker(marker, source, settings) is None


def test_clear_part_dir_keeps_hulls_a_marker_vouches_for(tmp_path):
    source, part_dir, part = _marker_fixture(tmp_path)
    settings = DecompositionSettings()
    _write_part_marker(part_dir / "part0005.json", source, settings, part)
    orphan = part_dir / "p999_hull000.obj"
    orphan.write_text("v 0 0 0\n", encoding="utf-8")

    _clear_part_dir(part_dir, source, settings)

    # Resumable work survives; hulls from a half-finished part do not.
    assert part.hulls[0].exists()
    assert not orphan.exists()


def test_clear_part_dir_drops_markers_from_an_earlier_generation(tmp_path):
    source, part_dir, part = _marker_fixture(tmp_path)
    marker = part_dir / "part0005.json"
    _write_part_marker(marker, source, DecompositionSettings(max_hulls=4), part)

    _clear_part_dir(part_dir, source, DecompositionSettings())

    assert not marker.exists()
    assert not part.hulls[0].exists()


def _touch(path, *, seconds=10):
    """Bump mtime without touching content, the way re-tessellation does."""

    stamp = path.stat().st_mtime_ns + seconds * 10**9
    os.utime(path, ns=(stamp, stamp))


def test_part_marker_survives_a_byte_identical_rewrite_of_the_source(tmp_path):
    source, part_dir, part = _marker_fixture(tmp_path)
    settings = DecompositionSettings()
    marker = part_dir / "part0005.json"
    _write_part_marker(marker, source, settings, part)

    _touch(source)

    # Re-tessellating the STEP rewrites identical bytes; that must not cost an 8 h rebuild.
    assert _read_part_marker(marker, source, settings) == part


def test_manifest_survives_a_byte_identical_rewrite_of_the_source(tmp_path):
    source, part_dir, part = _marker_fixture(tmp_path)
    settings = DecompositionSettings()
    manifest = part_dir / "manifest.json"
    _write_manifest(manifest, source, settings, [part])

    _touch(source)

    assert _read_manifest(manifest, source, settings) == [part]


def test_manifest_is_rejected_when_the_source_bytes_change(tmp_path):
    source, part_dir, part = _marker_fixture(tmp_path)
    settings = DecompositionSettings()
    manifest = part_dir / "manifest.json"
    _write_manifest(manifest, source, settings, [part])

    # Same byte count, different geometry: only the digest can tell these apart.
    source.write_text("v 0 0 0\nv 2 0 0\nv 0 2 0\nv 0 0 2\nf 1 2 3\n", encoding="utf-8")
    _touch(source)

    assert _read_manifest(manifest, source, settings) is None


def test_manifest_without_a_digest_still_validates_on_mtime(tmp_path):
    source, part_dir, part = _marker_fixture(tmp_path)
    settings = DecompositionSettings()
    manifest = part_dir / "manifest.json"
    _write_manifest(manifest, source, settings, [part])
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    del payload["source_sha256"]
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    assert _read_manifest(manifest, source, settings) == [part]
