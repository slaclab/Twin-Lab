"""Ground truth for the x-ray beam path, from geometry whose answer is known.

The propagation is a sphere march against Drake, so the cases here are built from shapes
whose blocking distance can be written down: a box at a known standoff stops a beam at
that standoff, and a plane at a known angle reflects into a known direction.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from twin_lab.beam import (
    CONTACT_EPSILON_M,
    Plane,
    bundle_offsets,
    cylinder_pose,
    intersect_plane,
    manifest_rotation,
    march,
    perpendicular_basis,
    propagate,
    reflect,
    top_face_plane,
)


def disc(height, radius=0.01, count=16, tilt=None):
    """A flat ring of vertices at ``height`` along z, optionally rotated out of plane."""

    angles = np.linspace(0.0, 2.0 * np.pi, count, endpoint=False)
    points = np.column_stack(
        [radius * np.cos(angles), radius * np.sin(angles), np.full(count, float(height))]
    )
    if tilt is not None:
        points = points @ np.asarray(tilt, dtype=float).T
    return points


class FakeResult:
    def __init__(self, identifier, distance):
        self.id_G = identifier
        self.distance = distance


class FakeQuery:
    """Signed distance to a set of world-space spheres, which is analytic."""

    def __init__(self, spheres):
        # spheres: {part: (centre, radius)}
        self.spheres = spheres
        self.calls = 0

    def ComputeSignedDistanceToPoint(self, point, threshold):
        self.calls += 1
        results = []
        for part, (centre, radius) in self.spheres.items():
            distance = float(np.linalg.norm(np.asarray(point) - np.asarray(centre)) - radius)
            if distance <= threshold:
                results.append(FakeResult(part, distance))
        return results


def identity_part(geometry_id):
    return geometry_id


def test_the_top_face_is_the_one_at_maximum_local_z():
    vertices = np.vstack([disc(0.0), disc(0.088)])
    plane = top_face_plane(vertices, [0.0, 0.0, 1.0])

    assert plane.origin_m == pytest.approx([0.0, 0.0, 0.088], abs=1e-9)
    assert plane.normal == pytest.approx([0.0, 0.0, 1.0])
    assert plane.radius_m == pytest.approx(0.01, rel=1e-6)


def test_the_face_follows_the_parts_own_axes_not_the_world():
    """A part lying on its side still exits along its local z, not world up."""

    angle = np.pi / 3.0
    tilt = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, np.cos(angle), -np.sin(angle)],
            [0.0, np.sin(angle), np.cos(angle)],
        ]
    )
    vertices = np.vstack([disc(0.0, tilt=tilt), disc(0.05, tilt=tilt)])

    plane = top_face_plane(vertices, tilt[:, 2])

    assert plane.normal == pytest.approx(tilt[:, 2])
    assert plane.origin_m == pytest.approx(tilt @ np.array([0.0, 0.0, 0.05]), abs=1e-9)


def test_a_face_needs_three_vertices_to_be_a_face():
    with pytest.raises(ValueError):
        top_face_plane(np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 1.0]]), [0.0, 0.0, 1.0])


def test_reflection_mirrors_the_normal_component_and_keeps_the_rest():
    direction = np.array([0.3, 0.0, -1.0])
    out = reflect(direction, [0.0, 0.0, 1.0])

    assert out == pytest.approx([0.3, 0.0, 1.0])
    assert np.linalg.norm(out) == pytest.approx(np.linalg.norm(direction))


def test_grazing_incidence_reflects_at_the_same_grazing_angle():
    normal = np.array([0.0, 0.0, 1.0])
    graze = np.radians(17.0)
    incoming = np.array([np.cos(graze), 0.0, -np.sin(graze)])

    outgoing = reflect(incoming, normal)

    assert np.degrees(np.arcsin(abs(outgoing @ normal))) == pytest.approx(17.0)


def test_a_ray_pointing_away_from_the_plane_never_meets_it():
    plane = Plane(np.array([0.0, 0.0, 1.0]), np.array([0.0, 0.0, 1.0]), 0.05)

    assert intersect_plane([0.0, 0.0, 0.0], [0.0, 0.0, -1.0], plane) is None


def test_the_plane_crossing_is_the_forward_distance():
    plane = Plane(np.array([0.0, 0.0, 1.0]), np.array([0.0, 0.0, 1.0]), 0.05)

    distance, point = intersect_plane([0.0, 0.0, 0.0], [0.0, 0.0, 1.0], plane)

    assert distance == pytest.approx(1.0)
    assert point == pytest.approx([0.0, 0.0, 1.0])


def test_the_march_stops_at_the_surface_of_the_obstruction():
    """A sphere of radius r centred d away stops a beam of radius b at d - r - b."""

    query = FakeQuery({"P001": (np.array([0.0, 0.0, 0.5]), 0.1)})

    reach, blocker = march(query, identity_part, [0, 0, 0], [0, 0, 1], 0.01)

    assert blocker == "P001"
    assert reach == pytest.approx(0.5 - 0.1 - 0.01, abs=2 * CONTACT_EPSILON_M)


def test_a_wider_beam_is_stopped_earlier_by_the_same_object():
    query = FakeQuery({"P001": (np.array([0.0, 0.0, 0.5]), 0.1)})

    narrow, _ = march(query, identity_part, [0, 0, 0], [0, 0, 1], 0.001)
    wide, _ = march(query, identity_part, [0, 0, 0], [0, 0, 1], 0.02)

    assert wide < narrow


def test_an_object_beside_the_beam_does_not_stop_it():
    """A sphere 0.5 m off axis is outside a 10 mm beam and must not register."""

    query = FakeQuery({"P001": (np.array([0.5, 0.0, 0.5]), 0.1)})

    reach, blocker = march(query, identity_part, [0, 0, 0], [0, 0, 1], 0.01, max_range_m=1.0)

    assert blocker is None
    assert reach == pytest.approx(1.0)


def test_the_emitter_can_be_excluded_so_it_does_not_block_its_own_beam():
    """The beam starts inside the optic, so without the exclusion step one reports it."""

    query = FakeQuery({"P_OPTIC": (np.array([0.0, 0.0, 0.0]), 0.02)})

    _, blocked = march(query, identity_part, [0, 0, 0], [0, 0, 1], 0.01, max_range_m=0.5)
    reach, ignored = march(
        query,
        identity_part,
        [0, 0, 0],
        [0, 0, 1],
        0.01,
        ignored_parts=frozenset({"P_OPTIC"}),
        max_range_m=0.5,
    )

    assert blocked == "P_OPTIC"
    assert ignored is None
    assert reach == pytest.approx(0.5)


def test_the_march_terminates_on_an_empty_scene():
    query = FakeQuery({})

    reach, blocker = march(query, identity_part, [0, 0, 0], [0, 0, 1], 0.01, max_range_m=2.0)

    assert blocker is None
    assert reach == pytest.approx(2.0)


def test_a_clear_beam_reflects_and_reports_two_segments():
    source = Plane(np.array([0.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0]), 0.011)
    # Face tilted 45 degrees, so an upward beam leaves along +x.
    normal = np.array([-1.0, 0.0, 1.0]) / np.sqrt(2.0)
    crystal = Plane(np.array([0.0, 0.0, 0.5]), normal, 0.014)

    path = propagate(
        FakeQuery({}),
        identity_part,
        name="South",
        source=source,
        crystal=crystal,
        radius_m=0.01,
    )

    assert path.reached_crystal
    assert not path.blocked
    assert len(path.rays) == 1
    assert len(path.rays[0].segments) == 2
    assert path.segments[0].length_m == pytest.approx(0.5)
    assert path.segments[1].direction == pytest.approx([1.0, 0.0, 0.0], abs=1e-9)


def test_an_obstruction_before_the_crystal_stops_the_beam_and_names_the_part():
    source = Plane(np.array([0.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0]), 0.011)
    crystal = Plane(np.array([0.0, 0.0, 0.5]), np.array([0.0, 0.0, -1.0]), 0.014)
    query = FakeQuery({"P660": (np.array([0.0, 0.0, 0.25]), 0.02)})

    path = propagate(
        query, identity_part, name="South", source=source, crystal=crystal, radius_m=0.01
    )

    assert path.blocked
    assert path.blocker == "P660"
    assert not path.reached_crystal
    assert len(path.segments) == 1
    assert "OBSTRUCTED" in path.summary()
    assert "P660" in path.summary()


def test_an_obstruction_after_the_crystal_is_reported_on_the_reflected_leg():
    source = Plane(np.array([0.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0]), 0.011)
    normal = np.array([-1.0, 0.0, 1.0]) / np.sqrt(2.0)
    crystal = Plane(np.array([0.0, 0.0, 0.5]), normal, 0.014)
    query = FakeQuery({"P783": (np.array([0.3, 0.0, 0.5]), 0.02)})

    path = propagate(
        query, identity_part, name="North", source=source, crystal=crystal, radius_m=0.01
    )

    assert path.reached_crystal
    assert path.blocker == "P783"
    assert path.segments[1].blocker == "P783"
    assert "after reflecting" in path.summary()
def test_a_beam_that_crosses_outside_the_face_is_a_miss_not_a_reflection():
    """The crystal face is 14 mm; a crossing 0.5 m off it must not bend the beam."""

    source = Plane(np.array([0.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0]), 0.011)
    crystal = Plane(np.array([0.5, 0.0, 0.5]), np.array([0.0, 0.0, -1.0]), 0.014)

    path = propagate(
        FakeQuery({}),
        identity_part,
        name="Middle",
        source=source,
        crystal=crystal,
        radius_m=0.01,
        max_range_m=1.5,
    )

    assert not path.reached_crystal
    assert not path.blocked
    assert len(path.segments) == 1
    assert path.segments[0].direction == pytest.approx([0.0, 0.0, 1.0])
    assert "never reaches the crystal" in path.summary()


def test_a_ray_that_misses_the_face_but_strikes_the_holder_still_reflects():
    """Otherwise there is no reflected leg to steer, and alignment has nothing to aim.

    The reflection is off the crystal plane at the point the holder was struck, so the
    leg exists to be walked onto the detector, but it is flagged as not on the face.
    """

    source = Plane(np.array([0.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0]), 0.011)
    normal = np.array([-1.0, 0.0, 1.0]) / np.sqrt(2.0)
    # Face centre far off the axis, so the crossing is a clean miss of the face.
    crystal = Plane(np.array([0.5, 0.0, 0.5]), normal, 0.014)
    query = FakeQuery({"P937": (np.array([0.0, 0.0, 0.35]), 0.05)})

    path = propagate(
        query,
        identity_part,
        name="South",
        source=source,
        crystal=crystal,
        radius_m=0.01,
        crystal_parts=frozenset({"P937"}),
    )

    assert path.reached_crystal
    assert path.on_face_rays == 0
    assert not path.rays[0].on_face
    assert len(path.rays[0].segments) == 2
    assert path.rays[0].segments[1].direction == pytest.approx([1.0, 0.0, 0.0], abs=1e-9)
    assert "reflecting off the crystal HOLDER" in path.summary()


def test_a_holder_reflection_is_drawn_amber_not_green():
    """The leg is usable for steering but its direction is not trustworthy yet."""

    from twin_lab.collision_viewer import OFF_FACE_BEAM_RGBA

    source = Plane(np.array([0.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0]), 0.011)
    normal = np.array([-1.0, 0.0, 1.0]) / np.sqrt(2.0)
    crystal = Plane(np.array([0.5, 0.0, 0.5]), normal, 0.014)
    query = FakeQuery({"P937": (np.array([0.0, 0.0, 0.35]), 0.05)})

    path = propagate(
        query,
        identity_part,
        name="South",
        source=source,
        crystal=crystal,
        radius_m=0.01,
        crystal_parts=frozenset({"P937"}),
    )
    colours = [colour for _, colour in _drawn(path).objects.values()]

    assert OFF_FACE_BEAM_RGBA in colours


def test_a_grazing_surface_terminates_instead_of_stalling():
    """Sphere marching creeps when the step shrinks toward zero without ever crossing.

    A surface a hair outside the beam gives step = clearance - radius, which tends to
    zero, so without a real contact cutoff the march burns its whole step budget.
    """

    # Sphere surface sits 0.1 mm outside a 10 mm beam, so the step never exceeds 0.1 mm.
    query = FakeQuery({"P664": (np.array([0.1101, 0.0, 0.5]), 0.1)})

    reach, blocker = march(query, identity_part, [0, 0, 0], [0, 0, 1], 0.01, max_range_m=1.0)

    assert blocker == "P664"
    assert reach < 1.0
    assert query.calls < 50


def test_the_probe_widens_until_it_finds_something_rather_than_stepping_blind():
    """A threshold that culls everything looks exactly like open space, so it must grow."""

    query = FakeQuery({"P001": (np.array([0.0, 0.0, 0.5]), 0.1)})

    reach, blocker = march(query, identity_part, [0, 0, 0], [0, 0, 1], 0.01)

    assert blocker == "P001"
    assert reach == pytest.approx(0.39, abs=1e-3)


def test_the_cylinder_pose_spans_the_segment():
    """Drake's cylinder is z-aligned about its centre, so the pose must carry both."""

    start = np.array([0.1, 0.2, 0.3])
    direction = np.array([0.0, 1.0, 1.0]) / np.sqrt(2.0)
    length = 0.4

    pose = cylinder_pose(start, direction, length)

    assert pose[:3, 3] == pytest.approx(start + direction * length / 2.0)
    assert pose[:3, 2] == pytest.approx(direction)
    # A rotation, so the axes stay orthonormal and right-handed.
    assert pose[:3, :3] @ pose[:3, :3].T == pytest.approx(np.eye(3), abs=1e-12)
    assert np.linalg.det(pose[:3, :3]) == pytest.approx(1.0)


def test_a_plane_moves_with_the_body_that_carries_it():
    plane = Plane(np.array([0.0, 0.0, 0.05]), np.array([0.0, 0.0, 1.0]), 0.014)
    pose = np.eye(4)
    pose[:3, :3] = np.array([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
    pose[:3, 3] = np.array([1.0, 2.0, 3.0])

    moved = plane.transformed(pose)

    assert moved.origin_m == pytest.approx([1.0, 2.0, 3.05])
    assert moved.normal == pytest.approx([0.0, 0.0, 1.0])
    assert moved.radius_m == plane.radius_m


def test_the_local_axes_come_from_the_manifest_occurrence_chain(tmp_path):
    """A part's own orientation is the product of its ancestors, not its own transform."""

    quarter = [[0.0, -1.0, 0.0, 0.0], [1.0, 0.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0, 0, 0, 1]]
    identity = np.eye(4).tolist()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "occurrences": [
                    {"id": "r", "parent_id": None, "ref": "A001", "transform_to_parent": identity},
                    {"id": "a", "parent_id": "r", "ref": "A002", "transform_to_parent": quarter},
                    {"id": "p", "parent_id": "a", "ref": "P100", "transform_to_parent": quarter},
                ]
            }
        ),
        encoding="utf-8",
    )

    rotation = manifest_rotation(manifest, "P100")

    # Two quarter turns about z: local x ends up along -x, and z is unchanged.
    assert rotation[:, 0] == pytest.approx([-1.0, 0.0, 0.0])
    assert rotation[:, 2] == pytest.approx([0.0, 0.0, 1.0])


def test_an_unknown_occurrence_is_an_error_not_a_silent_identity(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"occurrences": []}), encoding="utf-8")

    with pytest.raises(KeyError):
        manifest_rotation(manifest, "P999")


def test_the_bundle_tiles_the_aperture_without_spilling_outside_it():
    """Rings of 6j sub-beams, and the outermost must still fit inside the beam radius."""

    for rings, expected in ((0, 1), (1, 7), (2, 19), (3, 37)):
        offsets, sub_radius = bundle_offsets(0.01, rings)

        assert len(offsets) == expected
        assert sub_radius == pytest.approx(0.01 / (2 * rings + 1))
        reach = max(np.hypot(*offset) for offset in offsets) + sub_radius
        assert reach <= 0.01 + 1e-12


def test_the_sub_beams_are_laid_out_across_the_beam_not_along_it():
    direction = np.array([0.0, 0.0, 1.0])
    across, up = perpendicular_basis(direction)

    assert across @ direction == pytest.approx(0.0)
    assert up @ direction == pytest.approx(0.0)
    assert across @ up == pytest.approx(0.0)
    assert np.linalg.norm(across) == pytest.approx(1.0)
    assert np.linalg.norm(up) == pytest.approx(1.0)


def test_an_edge_across_half_the_aperture_stops_only_the_rays_it_covers():
    """The point of splitting the beam: one ray can only be wholly clear or wholly stopped."""

    source = Plane(np.array([0.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0]), 0.011)
    crystal = Plane(np.array([0.0, 0.0, 1.0]), np.array([0.0, 0.0, -1.0]), 0.014)
    # A sphere pushed off to +x so it covers one side of the bundle only.
    query = FakeQuery({"P664": (np.array([0.107, 0.0, 0.3]), 0.1)})

    path = propagate(
        query,
        identity_part,
        name="South",
        source=source,
        crystal=crystal,
        radius_m=0.01,
        subdivisions=1,
    )

    assert len(path.rays) == 7
    blocked = [ray for ray in path.rays if ray.blocker is not None]
    assert 0 < len(blocked) < 7
    assert f"{len(blocked)}/7 of the bundle" in path.summary()


def test_a_ray_landing_on_an_expected_part_is_not_an_obstruction():
    """Ending on the diode or the detector is the beam doing its job, not a fault."""

    source = Plane(np.array([0.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0]), 0.011)
    crystal = Plane(np.array([0.5, 0.0, 0.5]), np.array([0.0, 0.0, -1.0]), 0.014)
    query = FakeQuery({"P938": (np.array([0.0, 0.0, 0.4]), 0.05)})

    path = propagate(
        query,
        identity_part,
        name="South",
        source=source,
        crystal=crystal,
        radius_m=0.01,
        expected_parts=frozenset({"P938"}),
    )

    assert path.blocked
    assert path.blocker == "P938"
    assert path.obstructed_rays == 0
    assert path.obstructions == ()
    assert "OBSTRUCTED" not in path.summary()


def test_the_same_hit_on_an_unlisted_part_is_an_obstruction():
    """Identical geometry, different part: the verdict has to come from the list alone."""

    source = Plane(np.array([0.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0]), 0.011)
    crystal = Plane(np.array([0.5, 0.0, 0.5]), np.array([0.0, 0.0, -1.0]), 0.014)
    query = FakeQuery({"P664": (np.array([0.0, 0.0, 0.4]), 0.05)})

    path = propagate(
        query,
        identity_part,
        name="South",
        source=source,
        crystal=crystal,
        radius_m=0.01,
        expected_parts=frozenset({"P938"}),
    )

    assert path.obstructed_rays == len(path.rays)
    assert path.obstructions == ("P664",)
    assert "OBSTRUCTED fully" in path.summary()


def test_a_partly_aligned_bundle_reflects_some_rays_and_passes_the_rest():
    """A crystal face covering only part of the aperture splits the bundle in two."""

    source = Plane(np.array([0.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0]), 0.011)
    # Face centred on the bundle edge, so only the rays under it reflect.
    normal = np.array([-1.0, 0.0, 1.0]) / np.sqrt(2.0)
    crystal = Plane(np.array([0.0067, 0.0, 0.5]), normal, 0.005)

    path = propagate(
        FakeQuery({}),
        identity_part,
        name="Middle",
        source=source,
        crystal=crystal,
        radius_m=0.01,
        subdivisions=1,
    )

    landed = sum(1 for ray in path.rays if ray.on_face)
    assert 0 < landed < len(path.rays)
    assert f"{landed}/{len(path.rays)} of the bundle is on the crystal face" in path.summary()


class FakeMeshcat:
    """Records what the drawer would upload, so colour choice is testable without a browser."""

    def __init__(self):
        self.objects = {}
        self.visible = {}

    def SetObject(self, path, shape, rgba):
        self.objects[path] = (shape.length(), (rgba.r(), rgba.g(), rgba.b(), rgba.a()))

    def SetTransform(self, path, pose):
        pass

    def SetProperty(self, path, key, value):
        self.visible[path] = value


def _drawn(path):
    from twin_lab.collision_viewer import _BeamDrawer

    meshcat = FakeMeshcat()
    _BeamDrawer(meshcat).update([path])
    return meshcat


def test_a_ray_stopped_off_the_intended_path_is_drawn_red():
    from twin_lab.collision_viewer import (
        BEAM_RGBA,
        EXPECTED_BEAM_RGBA,
        OBSTRUCTED_BEAM_RGBA,
    )

    source = Plane(np.array([0.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0]), 0.011)
    crystal = Plane(np.array([0.5, 0.0, 0.5]), np.array([0.0, 0.0, -1.0]), 0.014)
    query = FakeQuery({"P664": (np.array([0.0, 0.0, 0.4]), 0.05)})
    common = dict(source=source, crystal=crystal, radius_m=0.01)

    obstruction = propagate(query, identity_part, name="A", **common)
    allowed = propagate(
        query, identity_part, name="B", expected_parts=frozenset({"P664"}), **common
    )
    unimpeded = propagate(FakeQuery({}), identity_part, name="C", max_range_m=0.3, **common)

    assert {colour for _, colour in _drawn(obstruction).objects.values()} == {
        OBSTRUCTED_BEAM_RGBA
    }
    assert {colour for _, colour in _drawn(allowed).objects.values()} == {EXPECTED_BEAM_RGBA}
    assert {colour for _, colour in _drawn(unimpeded).objects.values()} == {BEAM_RGBA}


def test_each_sub_beam_is_drawn_separately_so_partial_blocking_shows():
    source = Plane(np.array([0.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0]), 0.011)
    crystal = Plane(np.array([0.0, 0.0, 1.0]), np.array([0.0, 0.0, -1.0]), 0.014)
    query = FakeQuery({"P664": (np.array([0.107, 0.0, 0.3]), 0.1)})

    path = propagate(
        query,
        identity_part,
        name="South",
        source=source,
        crystal=crystal,
        radius_m=0.01,
        subdivisions=1,
    )
    meshcat = _drawn(path)

    from twin_lab.collision_viewer import OBSTRUCTED_BEAM_RGBA

    # A reflected ray draws two cylinders, so count rays by their path prefix.
    rays = {name.rsplit("/", 1)[0] for name in meshcat.objects}
    assert len(rays) == 7
    red = {
        name.rsplit("/", 1)[0]
        for name, (_, colour) in meshcat.objects.items()
        if colour == OBSTRUCTED_BEAM_RGBA
    }
    assert 0 < len(red) < 7
