"""Line-of-sight x-ray beam paths through the reviewed assembly.

The beam leaves a collimating optic along that part's local +z, reflects off the flat
face of a Bragg crystal, and stops at the first thing it touches. It is a mechanical
line-of-sight check, not an optical model: there is no energy, no Bragg acceptance and
no polycap divergence, so a segment that reaches the crystal proves only that nothing
is in the way.

Propagation is a sphere march against Drake's point signed-distance query. Drake has no
ray cast, but ``ComputeSignedDistanceToPoint`` returns the distance to the nearest
surface, which bounds how far the beam can advance before anything can possibly enter
it. The geometry it measures against is the CoACD hull set, and those hulls are a
measured superset of the parts, so a reported blockage is conservative in the same
direction as the clearance report: the beam can stop early, never late.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# The optic and crystal faces are both "the planar face normal to local z at maximum
# local z". Vertices there are coplanar to floating-point noise in every reviewed part,
# so the tolerance only has to survive the OBJ's 9-digit text round trip.
FACE_TOLERANCE_M = 1.0e-5
# A march step below this counts as contact. Sphere marching stalls against a near-grazing
# surface - the step shrinks toward zero without ever crossing - so the cutoff has to be
# real rather than epsilon. Half a millimetre sits inside the tessellation bias (~0.2 mm)
# and the hull margins (0.1-0.6 mm), and it errs toward reporting a blockage early.
CONTACT_EPSILON_M = 5.0e-4
# Probe thresholds for the point query. Cost climbs steeply with the threshold on this
# assembly (0.7 ms at 20 mm, 12.8 ms at 100 mm, 62 ms at 200 mm), so the march starts
# small and doubles only when it finds nothing, which keeps open space affordable without
# making the common tight case pay for it.
MIN_QUERY_M = 0.02
MAX_QUERY_M = 0.1
# Bound the march so a beam that escapes the assembly terminates instead of running away.
# The whole assembly measures about 1.3 m, so anything past this has left the experiment.
MAX_RANGE_M = 1.5
MAX_STEPS = 400


@dataclass(frozen=True)
class Plane:
    """A flat optical face: where it sits, which way it points, and how big it is."""

    origin_m: np.ndarray
    normal: np.ndarray
    radius_m: float

    def transformed(self, pose: np.ndarray) -> Plane:
        """This plane carried into another frame by a 4x4 rigid transform."""

        rotation = pose[:3, :3]
        return Plane(
            origin_m=rotation @ self.origin_m + pose[:3, 3],
            normal=rotation @ self.normal,
            radius_m=self.radius_m,
        )


@dataclass(frozen=True)
class Segment:
    """One straight run of a single ray, from where it started to where it stopped."""

    start_m: np.ndarray
    direction: np.ndarray
    length_m: float
    radius_m: float
    # The part that stopped this segment, or None when it reflected or ran out of range.
    blocker: str | None = None
    # True when the segment ended on the optic it was aimed at rather than an obstruction.
    reflected: bool = False
    # True when the blocker is a part this beam is supposed to land on - the crystal it
    # reflects from, its diode, or the detector at the end. Anything else is an obstruction.
    expected: bool = False

    @property
    def end_m(self) -> np.ndarray:
        return self.start_m + self.direction * self.length_m

    @property
    def obstructed(self) -> bool:
        return self.blocker is not None and not self.expected


@dataclass(frozen=True)
class Ray:
    """One sub-beam of the bundle: the thread of segments it followed."""

    segments: tuple[Segment, ...]

    @property
    def blocker(self) -> str | None:
        for segment in self.segments:
            if segment.blocker is not None:
                return segment.blocker
        return None

    @property
    def obstructed(self) -> bool:
        """Stopped by something that is not part of the intended optical path."""

        return any(segment.obstructed for segment in self.segments)

    @property
    def reached_crystal(self) -> bool:
        return any(segment.reflected for segment in self.segments)


@dataclass(frozen=True)
class BeamPath:
    """One beam, as the bundle of rays that tile its cross-section.

    Splitting the cross-section is what makes partial blockage visible: a single ray can
    only ever be all or nothing, whereas an edge clipping half the aperture stops half
    the bundle and leaves the rest running.
    """

    name: str
    rays: tuple[Ray, ...]

    @property
    def segments(self) -> tuple[Segment, ...]:
        return tuple(segment for ray in self.rays for segment in ray.segments)

    @property
    def blocked(self) -> bool:
        return any(ray.blocker is not None for ray in self.rays)

    @property
    def blocker(self) -> str | None:
        """The part that stopped the beam, or None when nothing did."""

        for ray in self.rays:
            if ray.blocker is not None:
                return ray.blocker
        return None

    @property
    def obstructed_rays(self) -> int:
        return sum(1 for ray in self.rays if ray.obstructed)

    @property
    def obstructions(self) -> tuple[str, ...]:
        """Distinct parts blocking this beam that are not on the intended path."""

        found = {
            segment.blocker
            for ray in self.rays
            for segment in ray.segments
            if segment.obstructed and segment.blocker is not None
        }
        return tuple(sorted(found))

    @property
    def reached_crystal(self) -> bool:
        return any(ray.reached_crystal for ray in self.rays)

    def summary(self) -> str:
        total = len(self.rays)
        obstructed = self.obstructed_rays
        if obstructed:
            share = "fully" if obstructed == total else f"{obstructed}/{total} of the bundle"
            where = "before the crystal" if not self.reached_crystal else "after reflecting"
            return (
                f"{self.name}: OBSTRUCTED {share} {where} by {', '.join(self.obstructions)}"
            )
        if not self.reached_crystal:
            return f"{self.name}: clear, but misses the crystal face"
        landed = sum(1 for ray in self.rays if ray.reached_crystal)
        if landed < total:
            return f"{self.name}: clear, {landed}/{total} of the bundle lands on the crystal"
        return f"{self.name}: clear, whole bundle lands on the crystal"


def top_face_plane(
    vertices: Sequence[Sequence[float]],
    local_z: Sequence[float],
    *,
    tolerance_m: float = FACE_TOLERANCE_M,
) -> Plane:
    """The planar face normal to ``local_z`` at the part's maximum extent along it.

    Both the collimating optic's exit window and the Bragg crystal's diffracting surface
    are defined this way, so they share one rule rather than two similar ones.
    """

    points = np.asarray(vertices, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3 or len(points) == 0:
        raise ValueError("vertices must be a non-empty Nx3 array")
    normal = np.asarray(local_z, dtype=float).reshape(3)
    norm = float(np.linalg.norm(normal))
    if norm == 0.0:
        raise ValueError("local_z must be a non-zero direction")
    normal = normal / norm

    heights = points @ normal
    on_face = points[heights > heights.max() - tolerance_m]
    if len(on_face) < 3:
        raise ValueError("fewer than 3 vertices lie on the maximum-z face")
    origin = on_face.mean(axis=0)
    radius = float(np.linalg.norm(on_face - origin, axis=1).max())
    return Plane(origin_m=origin, normal=normal, radius_m=radius)


def reflect(direction: Sequence[float], normal: Sequence[float]) -> np.ndarray:
    """Mirror a direction about a plane, as a specular reflection off the crystal face."""

    ray = np.asarray(direction, dtype=float).reshape(3)
    axis = np.asarray(normal, dtype=float).reshape(3)
    axis = axis / np.linalg.norm(axis)
    return ray - 2.0 * float(ray @ axis) * axis


def intersect_plane(
    origin: Sequence[float], direction: Sequence[float], plane: Plane
) -> tuple[float, np.ndarray] | None:
    """Forward distance and point where a ray crosses a plane, or None if it never does.

    Only the infinite plane is solved here; whether the hit lies inside the face is a
    separate question, because a beam that crosses the plane outside the crystal simply
    carries on rather than reflecting.
    """

    start = np.asarray(origin, dtype=float).reshape(3)
    ray = np.asarray(direction, dtype=float).reshape(3)
    denominator = float(ray @ plane.normal)
    if abs(denominator) < 1.0e-12:
        return None
    distance = float((plane.origin_m - start) @ plane.normal / denominator)
    if distance <= 0.0:
        return None
    return distance, start + ray * distance


def _nearest(
    query, part_of_geometry, point: np.ndarray, radius_m: float, ignored_parts: frozenset[str]
) -> tuple[float | None, str | None]:
    """Distance from a point to the nearest surface that is not excluded, and whose it is.

    The threshold grows until something is found, because a threshold that culls every
    geometry is indistinguishable from open space and would otherwise force a blind step.
    Always starting at the floor is deliberate: query cost is superlinear in the
    threshold, so the whole ladder up to 100 mm costs about what one 100 mm probe costs,
    and carrying a large threshold between steps measures slower (414 ms -> 950 ms).
    """

    threshold = max(2.0 * radius_m, MIN_QUERY_M)
    while True:
        nearest: float | None = None
        blocker: str | None = None
        for result in query.ComputeSignedDistanceToPoint(point, threshold):
            part = part_of_geometry(result.id_G)
            if part in ignored_parts:
                continue
            distance = float(result.distance)
            if nearest is None or distance < nearest:
                nearest = distance
                blocker = part
        if nearest is not None:
            return nearest, blocker
        if threshold >= MAX_QUERY_M:
            return None, None
        threshold = min(threshold * 2.0, MAX_QUERY_M)


def march(
    query,
    part_of_geometry,
    origin: Sequence[float],
    direction: Sequence[float],
    radius_m: float,
    *,
    ignored_parts: frozenset[str] = frozenset(),
    max_range_m: float = MAX_RANGE_M,
) -> tuple[float, str | None]:
    """Advance a beam of ``radius_m`` until something enters it.

    Returns how far it got and which part stopped it. Each step queries the distance from
    the beam axis to the nearest surface; nothing further away than that can reach the
    axis before the beam has travelled the same distance, so advancing by the clearance
    is safe and cannot step through a thin obstruction.
    """

    start = np.asarray(origin, dtype=float).reshape(3)
    ray = np.asarray(direction, dtype=float).reshape(3)
    ray = ray / np.linalg.norm(ray)

    travelled = 0.0
    for _ in range(MAX_STEPS):
        if travelled >= max_range_m:
            return max_range_m, None
        clearance, blocker = _nearest(
            query, part_of_geometry, start + ray * travelled, radius_m, ignored_parts
        )
        if clearance is None:
            travelled += MAX_QUERY_M
            continue
        step = clearance - radius_m
        if step <= CONTACT_EPSILON_M:
            return travelled, blocker
        travelled += step
    return min(travelled, max_range_m), None


def perpendicular_basis(direction: Sequence[float]) -> tuple[np.ndarray, np.ndarray]:
    """Two unit vectors spanning the plane across a direction. The beam has no roll."""

    axis = np.asarray(direction, dtype=float).reshape(3)
    axis = axis / np.linalg.norm(axis)
    reference = np.array([0.0, 0.0, 1.0]) if abs(axis[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    first = np.cross(reference, axis)
    first = first / np.linalg.norm(first)
    return first, np.cross(axis, first)


def bundle_offsets(radius_m: float, subdivisions: int) -> tuple[list[tuple[float, float]], float]:
    """Sub-beam centres and radius tiling the cross-section in hexagonal rings.

    ``subdivisions`` counts rings around the middle, so 0 is the whole aperture as one
    ray, 1 gives 7 sub-beams and 2 gives 19. Ring ``j`` sits at ``2 r j`` from the axis
    and the outermost sub-beam reaches ``r (2 k + 1)``, which is the full radius, so the
    bundle fills the aperture without spilling outside it.
    """

    rings = max(int(subdivisions), 0)
    sub_radius = radius_m / (2 * rings + 1)
    offsets = [(0.0, 0.0)]
    for ring in range(1, rings + 1):
        count = 6 * ring
        for index in range(count):
            angle = 2.0 * np.pi * index / count
            distance = 2.0 * sub_radius * ring
            offsets.append((distance * np.cos(angle), distance * np.sin(angle)))
    return offsets, sub_radius


def _ray_from(
    query,
    part_of_geometry,
    origin: np.ndarray,
    direction: np.ndarray,
    radius_m: float,
    crystal: Plane,
    *,
    source_parts: frozenset[str],
    crystal_parts: frozenset[str],
    expected_parts: frozenset[str],
    max_range_m: float,
) -> Ray:
    """Take one sub-beam from the optic to its crystal and on along the reflection."""

    def stop(blocker: str | None) -> bool:
        return blocker is not None and blocker in expected_parts

    hit = intersect_plane(origin, direction, crystal)
    reach, blocker = march(
        query,
        part_of_geometry,
        origin,
        direction,
        radius_m,
        ignored_parts=source_parts | crystal_parts,
        max_range_m=max_range_m if hit is None else hit[0],
    )
    if blocker is not None or hit is None:
        return Ray(
            (
                Segment(
                    start_m=origin,
                    direction=direction,
                    length_m=reach,
                    radius_m=radius_m,
                    blocker=blocker,
                    expected=stop(blocker),
                ),
            )
        )

    distance, point = hit
    # A crossing outside the crystal face is a miss: that sub-beam carries on undeflected,
    # which is how a partly-aligned bundle reflects some rays and passes the rest.
    if float(np.linalg.norm(point - crystal.origin_m)) > crystal.radius_m:
        onward, blocker = march(
            query,
            part_of_geometry,
            origin,
            direction,
            radius_m,
            ignored_parts=source_parts,
            max_range_m=max_range_m,
        )
        return Ray(
            (
                Segment(
                    start_m=origin,
                    direction=direction,
                    length_m=onward,
                    radius_m=radius_m,
                    blocker=blocker,
                    expected=stop(blocker),
                ),
            )
        )

    incoming = Segment(
        start_m=origin,
        direction=direction,
        length_m=distance,
        radius_m=radius_m,
        reflected=True,
    )
    outgoing_direction = reflect(direction, crystal.normal)
    outgoing_direction = outgoing_direction / np.linalg.norm(outgoing_direction)
    outgoing_reach, outgoing_blocker = march(
        query,
        part_of_geometry,
        point,
        outgoing_direction,
        radius_m,
        ignored_parts=crystal_parts,
        max_range_m=max_range_m,
    )
    outgoing = Segment(
        start_m=point,
        direction=outgoing_direction,
        length_m=outgoing_reach,
        radius_m=radius_m,
        blocker=outgoing_blocker,
        expected=stop(outgoing_blocker),
    )
    return Ray((incoming, outgoing))


def propagate(
    query,
    part_of_geometry,
    *,
    name: str,
    source: Plane,
    crystal: Plane,
    radius_m: float,
    source_parts: frozenset[str] = frozenset(),
    crystal_parts: frozenset[str] = frozenset(),
    expected_parts: frozenset[str] = frozenset(),
    subdivisions: int = 0,
    max_range_m: float = MAX_RANGE_M,
) -> BeamPath:
    """Run a beam from an optic to its crystal and onward along the reflected direction.

    The optic and the crystal holder are excluded from their own segments: the beam
    starts inside the optic's hull and ends on the crystal's, so without that the first
    step would report the emitter as the blocker.
    """

    direction = source.normal / np.linalg.norm(source.normal)
    offsets, sub_radius = bundle_offsets(radius_m, subdivisions)
    across, up = perpendicular_basis(direction)

    rays = tuple(
        _ray_from(
            query,
            part_of_geometry,
            source.origin_m + across * offset[0] + up * offset[1],
            direction,
            sub_radius,
            crystal,
            source_parts=source_parts,
            crystal_parts=crystal_parts,
            expected_parts=expected_parts,
            max_range_m=max_range_m,
        )
        for offset in offsets
    )
    return BeamPath(name=name, rays=rays)


def manifest_rotation(manifest_path: str | Path, ref: str) -> np.ndarray:
    """The 3x3 rotation taking a leaf occurrence's local axes into the STEP root frame.

    The part's local z is the axis both optical faces are defined against, and the
    manifest is the only place it survives: the cached meshes are already baked into the
    root frame, which throws each part's own orientation away.
    """

    occurrences = json.loads(Path(manifest_path).read_text(encoding="utf-8"))["occurrences"]
    by_id = {item["id"]: item for item in occurrences}
    matches = [item for item in occurrences if item.get("ref") == ref]
    if not matches:
        raise KeyError(f"occurrence {ref} is not in the manifest")

    chain = []
    node = matches[0]
    while node is not None:
        chain.append(node)
        node = by_id.get(node.get("parent_id"))

    transform = np.eye(4)
    for node in reversed(chain):
        transform = transform @ np.asarray(node["transform_to_parent"], dtype=float)
    return transform[:3, :3]


def face_from_cache(
    obj_path: str | Path,
    ref: str,
    manifest_path: str | Path,
    *,
    tolerance_m: float = FACE_TOLERANCE_M,
) -> Plane:
    """The optical face of one leaf part, in the STEP root frame.

    Taken from the tessellated stage-CAD mesh rather than the collision hulls: hulls are
    inflated by up to 0.6 mm, and that error would land directly in the reflected angle.
    """

    from .convex_collision import read_obj_parts

    for name, vertices, _ in read_obj_parts(Path(obj_path)):
        if name == ref:
            rotation = manifest_rotation(manifest_path, ref)
            return top_face_plane(vertices, rotation[:, 2], tolerance_m=tolerance_m)
    raise KeyError(f"part {ref} is not in {obj_path}")


def read_beam_config(path: str | Path) -> list[Mapping[str, object]]:
    """The ``beam_paths`` block of a reviewed inventory, or an empty list when absent."""

    import yaml

    document = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return list(document.get("beam_paths") or [])


@dataclass(frozen=True)
class BeamSpec:
    """One reviewed beam, resolved against a loaded plant.

    The two faces are held in the frame of the body that carries them, so a pose change
    only costs a transform lookup rather than re-reading any CAD.
    """

    name: str
    radius_m: float
    subdivisions: int
    source_body: str
    source_plane: Plane
    source_parts: frozenset[str]
    crystal_body: str
    crystal_plane: Plane
    crystal_parts: frozenset[str]
    # Parts the beam is meant to land on, so stopping there is not an obstruction.
    expected_parts: frozenset[str]


def body_of_part(model, ref: str) -> str:
    """The compiled link that carries a reviewed occurrence's collision geometry."""

    from pydrake.geometry import Role

    from .collision import part_of

    plant = model.scene.plant
    inspector = model.scene.scene_graph.model_inspector()
    for geometry_id in inspector.GetAllGeometryIds(Role.kProximity):
        if part_of(inspector.GetName(geometry_id)).upper() != ref.upper():
            continue
        return plant.GetBodyFromFrameId(inspector.GetFrameId(geometry_id)).name()
    raise KeyError(f"no collision geometry carries part {ref}")


def pose_in_world(model, body_name: str) -> np.ndarray:
    """The 4x4 world pose of a compiled link at the model's current joint positions."""

    plant = model.scene.plant
    plant_context = plant.GetMyContextFromRoot(model.context)
    return plant.GetBodyByName(body_name).EvalPoseInWorld(plant_context).GetAsMatrix4()


def resolve_beams(
    model,
    config: Iterable[Mapping[str, object]],
    *,
    cache_dir: str | Path,
    manifest_path: str | Path,
) -> list[BeamSpec]:
    """Bind a reviewed ``beam_paths`` block to a loaded plant.

    The faces are cut from the stage-CAD meshes, which live in the STEP root frame, and
    the plant's zero configuration *is* that pose, so the world pose of each carrying
    body at zero is exactly the root-to-body transform needed to pin the face to its
    body. Anything that moves a joint afterwards then carries the face with it.
    """

    plant = model.scene.plant
    plant_context = plant.GetMyMutableContextFromRoot(model.context)
    held = plant.GetPositions(plant_context).copy()
    plant.SetPositions(plant_context, np.zeros_like(held))
    try:
        specs = []
        for entry in config:
            specs.append(_resolve_one(model, entry, Path(cache_dir), Path(manifest_path)))
    finally:
        plant.SetPositions(plant_context, held)
    return specs


def _resolve_one(model, entry: Mapping[str, object], cache_dir: Path, manifest: Path) -> BeamSpec:
    def face(role: str) -> tuple[str, Plane, frozenset[str]]:
        section = entry[role]
        ref = str(section["ref"])
        plane_root = face_from_cache(cache_dir / str(section["mesh"]), ref, manifest)
        body = body_of_part(model, ref)
        # World at the plant's zero is the STEP root frame, so inverting the body pose
        # there converts a root-frame face into the body frame that carries it.
        inverse = np.linalg.inv(pose_in_world(model, body))
        ignored = {ref.upper()} | {str(x).upper() for x in section.get("ignore", [])}
        return body, plane_root.transformed(inverse), frozenset(ignored)

    source_body, source_plane, source_parts = face("source")
    crystal_body, crystal_plane, crystal_parts = face("crystal")
    expected = {str(ref).upper() for ref in entry.get("expected", [])} | crystal_parts
    return BeamSpec(
        name=str(entry.get("name", "beam")),
        radius_m=float(entry.get("diameter_mm", 20.0)) / 2000.0,
        subdivisions=int(entry.get("subdivisions", 1)),
        source_body=source_body,
        source_plane=source_plane,
        source_parts=source_parts,
        crystal_body=crystal_body,
        crystal_plane=crystal_plane,
        crystal_parts=crystal_parts,
        expected_parts=frozenset(expected),
    )


def trace(model, specs: Iterable[BeamSpec], *, max_range_m: float = MAX_RANGE_M) -> list[BeamPath]:
    """Propagate every reviewed beam at the model's current pose."""

    from pydrake.geometry import QueryObject

    from .collision import part_of

    scene_graph = model.scene.scene_graph
    scene_context = scene_graph.GetMyContextFromRoot(model.context)
    query: QueryObject = scene_graph.get_query_output_port().Eval(scene_context)
    inspector = query.inspector()
    names: dict[object, str] = {}

    def part_of_geometry(geometry_id):
        cached = names.get(geometry_id)
        if cached is None:
            cached = part_of(inspector.GetName(geometry_id)).upper()
            names[geometry_id] = cached
        return cached

    paths = []
    for spec in specs:
        source = spec.source_plane.transformed(pose_in_world(model, spec.source_body))
        crystal = spec.crystal_plane.transformed(pose_in_world(model, spec.crystal_body))
        paths.append(
            propagate(
                query,
                part_of_geometry,
                name=spec.name,
                source=source,
                crystal=crystal,
                radius_m=spec.radius_m,
                source_parts=spec.source_parts,
                crystal_parts=spec.crystal_parts,
                expected_parts=spec.expected_parts,
                subdivisions=spec.subdivisions,
                max_range_m=max_range_m,
            )
        )
    return paths


def cylinder_pose(
    start: Sequence[float], direction: Sequence[float], length_m: float
) -> np.ndarray:
    """A 4x4 placing Drake's z-aligned, centre-origin cylinder along a beam segment."""

    origin = np.asarray(start, dtype=float).reshape(3)
    axis = np.asarray(direction, dtype=float).reshape(3)
    axis = axis / np.linalg.norm(axis)
    first, second = perpendicular_basis(axis)

    pose = np.eye(4)
    pose[:3, 0] = first
    pose[:3, 1] = second
    pose[:3, 2] = axis
    pose[:3, 3] = origin + axis * (length_m / 2.0)
    return pose


def describe(paths: Iterable[BeamPath]) -> str:
    return "\n".join(path.summary() for path in paths)
