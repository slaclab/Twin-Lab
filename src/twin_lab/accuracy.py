"""Measure what the clearance report is actually worth, against ground truth it cannot see.

Two questions have to be answered separately before an accuracy figure means anything.

*Does the pipeline ever miss an interference?* The shipped path is a chain of things that
can silently drop a pair: Drake's collision filters, the reviewed ``ignored_pairs``, the
warning band, and the neighbourhood truncation in the CAD re-check. A bug in any of them
looks exactly like a clean report. So this module rebuilds the answer from the tessellated
parts alone, with no Drake, no hulls and no filters, and compares. Every pair the oracle
puts in contact and the pipeline does not report is a false negative, and the count over a
sample of poses is the number that can be quoted.

*How far is the tessellation itself from the CAD?* The oracle shares the pipeline's meshes,
so it says nothing about the 2 mm linear deflection they were built at. That is measured by
re-cutting the same solids finer and watching the reported gap converge.

The oracle is exact rather than sampled. Two features closer than ``warn_m`` both lie inside
the parts' bounding-box overlap grown by ``warn_m``, so restricting each mesh to the
triangles reaching that box discards nothing that could have been the answer.
"""

from __future__ import annotations

import argparse
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .clearance_refine import mesh_separation_m
from .collision import ClearanceReport, CollisionModel, part_of
from .paths import CACHE_ROOT, resolve_repo_path

MM_PER_M = 1000.0
# Triangle pairs a single direct distance call may take on. Above this the shared box is
# halved instead; below it the split bookkeeping costs more than the arithmetic saves.
TRIANGLE_PAIR_BUDGET = 40_000
# Backstop on the box splitting. The band floor below already bounds the depth for any real
# assembly; this only catches a mesh whose bounds do not shrink under a cut.
MAX_SPLIT_DEPTH = 64
# Deflections for the convergence study, coarsest first. The first is what the shipped
# package is built at, so every later row is the error of the one before it.
DEFAULT_DEFLECTIONS_MM = (2.0, 1.0, 0.5, 0.2, 0.1)


@dataclass(frozen=True)
class PartFrame:
    """Where one reviewed part's cached mesh sits in the world at the current pose."""

    ref: str
    pose: np.ndarray
    body: int


@dataclass(frozen=True)
class PoseAudit:
    """One sampled configuration, with the pipeline's verdict beside the oracle's."""

    positions: Mapping[str, float]
    warn_m: float
    reported: frozenset[tuple[str, str]]
    oracle: Mapping[tuple[str, str], float]
    ignored: frozenset[tuple[str, str]]
    candidates: int

    @property
    def oracle_contacts(self) -> dict[tuple[str, str], float]:
        return {pair: gap for pair, gap in self.oracle.items() if gap <= 0.0}

    @property
    def missed(self) -> tuple[tuple[str, str], ...]:
        """Real contacts the pipeline neither reported nor was told to ignore."""

        return tuple(sorted(set(self.oracle_contacts) - self.reported - self.ignored))

    @property
    def suppressed(self) -> tuple[tuple[str, str], ...]:
        """Real contacts hidden by a reviewed ``ignored_pairs`` entry rather than by a bug."""

        return tuple(sorted(set(self.oracle_contacts) & self.ignored))

    @property
    def spurious(self) -> tuple[tuple[str, str], ...]:
        """Pairs the hulls put inside the band that the CAD says are further apart."""

        return tuple(sorted(self.reported - set(self.oracle)))


@dataclass
class AccuracyResult:
    """The audit over every sampled pose."""

    audits: list[PoseAudit] = field(default_factory=list)

    @property
    def missed(self) -> int:
        return sum(len(audit.missed) for audit in self.audits)

    @property
    def suppressed(self) -> int:
        return sum(len(audit.suppressed) for audit in self.audits)

    @property
    def contacts(self) -> int:
        return sum(len(audit.oracle_contacts) for audit in self.audits)

    @property
    def reported(self) -> int:
        return sum(len(audit.reported) for audit in self.audits)

    @property
    def spurious(self) -> int:
        return sum(len(audit.spurious) for audit in self.audits)

    def summary(self) -> str:
        poses = len(self.audits)
        detected = self.contacts - self.missed - self.suppressed
        rate = "n/a" if not self.contacts else f"{100.0 * detected / self.contacts:.1f}%"
        return (
            f"{poses} poses: oracle found {self.contacts} contacting part pairs, "
            f"pipeline caught {detected} ({rate}), missed {self.missed}, "
            f"{self.suppressed} suppressed by review; "
            f"{self.spurious} of {self.reported} reported pairs were hull artefacts"
        )


def part_geometries(model: CollisionModel):
    """One representative collision geometry per part, with its rigid body.

    Every hull of a part hangs off the same body, and Drake's filters are declared over
    bodies, so one geometry decides the pair's fate for the whole part.
    """

    from pydrake.geometry import Role

    scene = model.scene
    scene_context = scene.scene_graph.GetMyContextFromRoot(model.context)
    query = scene.scene_graph.get_query_output_port().Eval(scene_context)
    inspector = query.inspector()
    chosen: dict[str, tuple[object, int]] = {}
    for geometry_id in inspector.GetAllGeometryIds(Role.kProximity):
        ref = part_of(inspector.GetName(geometry_id)).upper()
        if ref in chosen:
            continue
        body = scene.plant.GetBodyFromFrameId(inspector.GetFrameId(geometry_id))
        chosen[ref] = (geometry_id, int(body.index()))
    return query, inspector, chosen


@dataclass(frozen=True)
class FilterCoverage:
    """Which part pairs the collision query will actually ever look at.

    A hull encloses its part, so a pair the query does examine cannot be missed. That makes
    the whole no-false-negative claim rest on this: every pair of parts that can move
    relative to one another has to survive Drake's filters. Parts welded into one body are
    excluded because no joint can bring them together; if they interfere it is a fact about
    the CAD, not about the machine's travel.
    """

    movable_pairs: int
    adjacent: tuple[tuple[str, str], ...]
    unexplained: tuple[tuple[str, str], ...]
    ignored: tuple[tuple[str, str], ...]

    @property
    def covered(self) -> int:
        return self.movable_pairs - len(self.adjacent) - len(self.unexplained) - len(self.ignored)

    def summary(self) -> str:
        return (
            f"{self.covered} of {self.movable_pairs} part pairs that can move relative to "
            f"one another are checked; {len(self.adjacent)} hidden by Drake's joint "
            f"adjacency, {len(self.unexplained)} filtered with no joint to explain it, "
            f"{len(self.ignored)} whitelisted by review"
        )


def _joint_adjacent_bodies(model: CollisionModel) -> set[tuple[int, int]]:
    """Body pairs sitting either side of one joint, which Drake filters by default."""

    from pydrake.multibody.tree import JointIndex

    plant = model.scene.plant
    pairs = set()
    for index in range(plant.num_joints()):
        joint = plant.get_joint(JointIndex(index))
        parent = int(joint.parent_body().index())
        child = int(joint.child_body().index())
        pairs.add((min(parent, child), max(parent, child)))
    return pairs


def filter_coverage(model: CollisionModel) -> FilterCoverage:
    """Exhaustively confirm no pair of independently moving parts is hidden from the query."""

    _, inspector, chosen = part_geometries(model)
    adjacent_bodies = _joint_adjacent_bodies(model)
    refs = sorted(chosen)
    movable = 0
    adjacent: list[tuple[str, str]] = []
    unexplained: list[tuple[str, str]] = []
    ignored: list[tuple[str, str]] = []
    for index, first in enumerate(refs):
        first_id, first_body = chosen[first]
        for second in refs[index + 1 :]:
            second_id, second_body = chosen[second]
            if first_body == second_body:
                continue
            movable += 1
            pair = (first, second)
            if pair in model.ignored_pairs:
                ignored.append(pair)
            elif inspector.CollisionFiltered(first_id, second_id):
                bodies = (min(first_body, second_body), max(first_body, second_body))
                (adjacent if bodies in adjacent_bodies else unexplained).append(pair)
    return FilterCoverage(
        movable_pairs=movable,
        adjacent=tuple(adjacent),
        unexplained=tuple(unexplained),
        ignored=tuple(ignored),
    )


def part_frames(model: CollisionModel) -> dict[str, PartFrame]:
    """World pose and rigid body of every part carrying collision geometry.

    All of a part's hulls were cut from one mesh in one frame, so any of its geometries
    gives the transform that mesh needs. The body index rides along because two parts
    welded into the same body cannot approach each other and their contact, if any, is a
    fact about the CAD rather than about the machine's travel.
    """

    from pydrake.geometry import Role

    scene = model.scene
    scene_context = scene.scene_graph.GetMyContextFromRoot(model.context)
    query = scene.scene_graph.get_query_output_port().Eval(scene_context)
    inspector = query.inspector()
    frames: dict[str, PartFrame] = {}
    for geometry_id in inspector.GetAllGeometryIds(Role.kProximity):
        ref = part_of(inspector.GetName(geometry_id)).upper()
        if ref in frames:
            continue
        body = scene.plant.GetBodyFromFrameId(inspector.GetFrameId(geometry_id))
        frames[ref] = PartFrame(
            ref=ref,
            pose=query.GetPoseInWorld(geometry_id).GetAsMatrix4(),
            body=int(body.index()),
        )
    return frames


def triangles_in_box(
    vertices: np.ndarray, faces: np.ndarray, lower: np.ndarray, upper: np.ndarray
) -> np.ndarray:
    """Faces whose bounding box reaches into an axis-aligned box."""

    if len(faces) == 0:
        return faces
    corners = vertices[faces]
    return faces[_reaching(corners.min(axis=1), corners.max(axis=1), lower, upper)]


def _reaching(
    face_lower: np.ndarray, face_upper: np.ndarray, lower: np.ndarray, upper: np.ndarray
) -> np.ndarray:
    return np.all((face_upper >= lower) & (face_lower <= upper), axis=1)


@dataclass(frozen=True)
class WorldMesh:
    """One part's triangles placed in the world, with the per-face bounds cached.

    The bounds are the reason this is a class: a part is tested against every neighbour it
    might reach, and rebuilding the corner array of a chamber-sized mesh once per neighbour
    costs more than the distances do.
    """

    vertices: np.ndarray
    faces: np.ndarray
    face_lower: np.ndarray
    face_upper: np.ndarray
    lower: np.ndarray
    upper: np.ndarray

    @classmethod
    def place(cls, mesh: tuple[np.ndarray, np.ndarray], pose: np.ndarray) -> WorldMesh:
        vertices, faces = mesh
        world = vertices @ pose[:3, :3].T + pose[:3, 3]
        corners = world[faces]
        face_lower, face_upper = corners.min(axis=1), corners.max(axis=1)
        return cls(
            vertices=world,
            faces=faces,
            face_lower=face_lower,
            face_upper=face_upper,
            lower=world.min(axis=0),
            upper=world.max(axis=0),
        )

    def near(self, lower: np.ndarray, upper: np.ndarray) -> np.ndarray:
        return self.faces[_reaching(self.face_lower, self.face_upper, lower, upper)]

    def within(self, index: np.ndarray, lower: np.ndarray, upper: np.ndarray) -> np.ndarray:
        keep = _reaching(self.face_lower[index], self.face_upper[index], lower, upper)
        return index[keep]


def separation_m(
    a: WorldMesh,
    b: WorldMesh,
    *,
    warn_m: float,
    budget: int = TRIANGLE_PAIR_BUDGET,
) -> float:
    """Exact separation of two placed meshes, by splitting the space they share.

    Parts that are bolted around one another share almost all of their bounding box, so the
    box test alone can leave tens of thousands of triangles a side and a direct answer costs
    billions of triangle pairs. Halving the box and growing each half by the distance still
    worth finding keeps every feature pair that could beat it on at least one side of the
    cut, so the smallest answer over the halves is still the exact one. Anything past
    ``warn_m`` is reported as ``warn_m``: the caller only has to know the pair is outside
    the band.
    """

    return _split_separation(
        a, np.arange(len(a.faces)), b, np.arange(len(b.faces)), warn_m, warn_m, budget, 0
    )


def _split_separation(
    a: WorldMesh,
    a_index: np.ndarray,
    b: WorldMesh,
    b_index: np.ndarray,
    limit: float,
    warn_m: float,
    budget: int,
    depth: int,
) -> float:
    """Smallest separation below ``limit``, or ``limit`` when there is none.

    The limit tightens as the search finds better answers, and it drives the boxes: two
    features closer than it both lie in the overlap of their sets' bounds grown by it, so
    that overlap is the only space left to search.
    """

    if len(a_index) == 0 or len(b_index) == 0:
        return limit
    a_lower, a_upper = a.face_lower[a_index].min(axis=0), a.face_upper[a_index].max(axis=0)
    b_lower, b_upper = b.face_lower[b_index].min(axis=0), b.face_upper[b_index].max(axis=0)
    if max(np.max(a_lower - b_upper), np.max(b_lower - a_upper)) >= limit:
        return limit

    lower = np.maximum(a_lower, b_lower) - limit
    upper = np.minimum(a_upper, b_upper) + limit
    a_index = a.within(a_index, lower, upper)
    b_index = b.within(b_index, lower, upper)
    if len(a_index) == 0 or len(b_index) == 0:
        return limit
    axis = int(np.argmax(upper - lower))
    # A half is grown by the limit, so it is only smaller than its parent while the parent
    # is several bands wide. Splitting below that converges on the floor without ever
    # reaching it, which is an infinite descent rather than a slow one.
    if (
        len(a_index) * len(b_index) <= budget
        or (upper - lower)[axis] <= 4.0 * warn_m
        or depth >= MAX_SPLIT_DEPTH
    ):
        return min(
            limit,
            mesh_separation_m(a.vertices, a.faces[a_index], b.vertices, b.faces[b_index]),
        )

    for half_lower, half_upper in _halves(lower, upper, axis, limit):
        limit = _split_separation(
            a,
            a.within(a_index, half_lower, half_upper),
            b,
            b.within(b_index, half_lower, half_upper),
            limit,
            warn_m,
            budget,
            depth + 1,
        )
        if limit <= 0.0:
            return 0.0
    return limit


def _halves(
    lower: np.ndarray, upper: np.ndarray, axis: int, growth: float
) -> tuple[tuple[np.ndarray, np.ndarray], tuple[np.ndarray, np.ndarray]]:
    """The box cut in two along ``axis``, each half grown so neither loses a close pair."""

    middle = 0.5 * (lower[axis] + upper[axis])
    low_upper = upper.copy()
    low_upper[axis] = middle + growth
    high_lower = lower.copy()
    high_lower[axis] = middle - growth
    return (lower, low_upper), (high_lower, upper)


def oracle_distances(
    model: CollisionModel, *, warn_m: float = 0.005
) -> tuple[dict[tuple[str, str], float], int]:
    """Exact part-to-part separations within ``warn_m``, from the meshes alone.

    Returns the distances keyed by sorted part pair, and how many pairs had to be measured.
    """

    refiner = model.refiner
    if refiner is None:
        raise ValueError("The oracle needs the decomposition cache; pass decomposition_dir")

    frames = part_frames(model)
    world: dict[str, WorldMesh] = {}
    for ref, frame in frames.items():
        mesh = refiner.part_mesh(ref)
        if mesh is not None:
            world[ref] = WorldMesh.place(mesh, frame.pose)

    refs = sorted(world)
    if not refs:
        return {}, 0
    lowers = np.array([world[ref].lower for ref in refs])
    uppers = np.array([world[ref].upper for ref in refs])
    bodies = np.array([frames[ref].body for ref in refs])

    # Per-axis separation of every box pair at once; the largest axis gap is the gap.
    gaps = np.maximum(
        lowers[:, None, :] - uppers[None, :, :], lowers[None, :, :] - uppers[:, None, :]
    ).max(axis=2)
    close = np.triu((gaps <= warn_m) & (bodies[:, None] != bodies[None, :]), k=1)

    distances: dict[tuple[str, str], float] = {}
    for i, j in zip(*np.nonzero(close), strict=True):
        distance = separation_m(world[refs[i]], world[refs[j]], warn_m=warn_m)
        if distance < warn_m:
            distances[tuple(sorted((refs[i], refs[j])))] = distance
    return distances, int(close.sum())


def reported_pairs(report: ClearanceReport, warn_m: float) -> frozenset[tuple[str, str]]:
    """Part pairs the pipeline put inside the band, sorted so they compare with the oracle."""

    return frozenset(
        tuple(sorted(part.upper() for part in item.parts))
        for item in report.clearances
        if item.distance_m <= warn_m
    )


def audit_pose(
    model: CollisionModel, positions: Mapping[str, float], *, warn_m: float = 0.005
) -> PoseAudit:
    """Compare the shipped broad phase against the oracle at one configuration.

    The raw report is the right thing to judge: the CAD re-check only ever widens a gap,
    so a pair the broad phase never returned can never be recovered downstream.
    """

    model.set_positions(positions)
    report = model.report(warn_m=warn_m)
    distances, candidates = oracle_distances(model, warn_m=warn_m)
    return PoseAudit(
        positions=dict(positions),
        warn_m=warn_m,
        reported=reported_pairs(report, warn_m),
        oracle=distances,
        ignored=model.ignored_pairs,
        candidates=candidates,
    )


def sample_positions(
    model: CollisionModel, count: int, *, seed: int = 0
) -> list[dict[str, float]]:
    """The all-zero pose followed by ``count`` configurations drawn from the joint limits."""

    from pydrake.multibody.tree import JointIndex

    plant = model.scene.plant
    limits: list[tuple[str, float, float]] = []
    for index in range(plant.num_joints()):
        joint = plant.get_joint(JointIndex(index))
        if joint.num_positions() != 1:
            continue
        limits.append(
            (
                joint.name(),
                float(joint.position_lower_limits()[0]),
                float(joint.position_upper_limits()[0]),
            )
        )
    rng = np.random.default_rng(seed)
    poses = [{name: 0.0 for name, _, _ in limits}]
    for _ in range(count):
        poses.append({name: float(rng.uniform(low, high)) for name, low, high in limits})
    return poses


def audit(
    model: CollisionModel,
    poses: Sequence[Mapping[str, float]],
    *,
    warn_m: float = 0.005,
    on_pose=None,
) -> AccuracyResult:
    """Run the oracle comparison over a set of configurations."""

    result = AccuracyResult()
    for index, positions in enumerate(poses):
        pose_audit = audit_pose(model, positions, warn_m=warn_m)
        result.audits.append(pose_audit)
        if on_pose is not None:
            on_pose(index, pose_audit)
    return result


def convergence(
    model: CollisionModel,
    step_path: Path,
    pairs: Iterable[tuple[str, str]],
    *,
    deflections_mm: Sequence[float] = DEFAULT_DEFLECTIONS_MM,
    warn_m: float = 0.005,
) -> dict[tuple[str, str], list[float]]:
    """Re-cut the named parts from the STEP at each deflection and re-measure their gap.

    The pipeline's meshes and the oracle's are the same triangles, so neither can see the
    error of the tessellation they share. Cutting the same solids finer and watching the
    gap settle turns that shared blind spot into a measured bound.
    """

    import tempfile

    from .cad_geometry import leaf_occurrences, write_group_obj
    from .constraints_wizard import _read_step_document
    from .convex_collision import read_obj_parts

    wanted: set[str] = set()
    for first, second in pairs:
        wanted.update((first.upper(), second.upper()))
    frames = part_frames(model)
    document, _, roots = _read_step_document(step_path)
    assert document is not None  # Keep the XCAF labels alive while the shapes are meshed.
    occurrences = leaf_occurrences(roots)
    missing = wanted - set(occurrences)
    if missing:
        raise ValueError(f"STEP has no occurrence for {sorted(missing)}")

    results: dict[tuple[str, str], list[float]] = {tuple(sorted(pair)): [] for pair in pairs}
    with tempfile.TemporaryDirectory() as scratch:
        for deflection in deflections_mm:
            output = Path(scratch) / f"cut_{deflection}.obj"
            write_group_obj(
                [occurrences[ref] for ref in sorted(wanted)],
                output,
                linear_deflection_mm=deflection,
            )
            placed = {
                reference.upper(): WorldMesh.place(
                    (
                        np.asarray(vertices, dtype=np.float64),
                        np.asarray(faces, dtype=np.int32),
                    ),
                    frames[reference.upper()].pose,
                )
                for reference, vertices, faces in read_obj_parts(output)
                if reference.upper() in wanted
            }
            for first, second in results:
                results[first, second].append(
                    separation_m(placed[first], placed[second], warn_m=warn_m)
                )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure the clearance report against independent ground truth."
    )
    parser.add_argument("package", help="Compiled SDF package directory")
    parser.add_argument("--inventory", required=True, help="Reviewed inventory YAML")
    parser.add_argument(
        "--decomposition-dir",
        help="Hull cache the package was compiled from (default: derived from its name)",
    )
    parser.add_argument("--poses", type=int, default=20, help="Random configurations to sample")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--warn-mm", type=float, default=5.0)
    parser.add_argument(
        "--convergence",
        metavar="STEP",
        help="Also re-cut the closest pairs from this STEP at finer deflections",
    )
    args = parser.parse_args()

    package = resolve_repo_path(args.package)
    sdf = next(path for path in sorted(package.glob("*.sdf")) if "matlab" not in path.stem)
    warn_m = args.warn_mm / MM_PER_M
    decomposition_dir = (
        resolve_repo_path(args.decomposition_dir)
        if args.decomposition_dir
        else CACHE_ROOT / "convex-collision" / package.name.removesuffix(".collision")
    )
    model = CollisionModel.load(
        sdf,
        ignore_file=args.inventory,
        label_source=args.inventory,
        decomposition_dir=decomposition_dir,
    )

    def announce(index: int, pose: PoseAudit) -> None:
        flag = f"  MISSED {len(pose.missed)}" if pose.missed else ""
        print(
            f"  pose {index:>3}: {len(pose.oracle_contacts):>3} real contacts, "
            f"{len(pose.reported):>3} reported, {pose.candidates:>4} pairs measured{flag}",
            flush=True,
        )

    poses = sample_positions(model, args.poses, seed=args.seed)
    print(f"Auditing {len(poses)} poses against the tessellated CAD", flush=True)
    result = audit(model, poses, warn_m=warn_m, on_pose=announce)
    print(f"\n{result.summary()}")
    for index, pose in enumerate(result.audits):
        for pair in pose.missed:
            print(f"  FALSE NEGATIVE pose {index}: {pair}")
        for pair in pose.suppressed:
            gap = pose.oracle_contacts[pair] * MM_PER_M
            print(f"  suppressed by review, pose {index}: {pair} at {gap:+.2f} mm")

    if args.convergence:
        worst = _closest_pairs(result)
        print(f"\nTessellation convergence for {len(worst)} closest pairs")
        table = convergence(model, resolve_repo_path(args.convergence), worst)
        header = "  ".join(f"{value:>6.2f} mm" for value in DEFAULT_DEFLECTIONS_MM)
        print(f"{'pair':<16}{header}")
        for pair, distances in table.items():
            row = "  ".join(f"{value * MM_PER_M:>+9.3f}" for value in distances)
            print(f"{pair[0] + '/' + pair[1]:<16}{row}")


def _closest_pairs(result: AccuracyResult, limit: int = 6) -> list[tuple[str, str]]:
    """The tightest part pairs the oracle saw, which is where deflection matters most."""

    best: dict[tuple[str, str], float] = {}
    for pose in result.audits:
        for pair, gap in pose.oracle.items():
            best[pair] = min(gap, best.get(pair, math.inf))
    if not best:
        return []
    return sorted(best, key=lambda pair: best[pair])[:limit]


if __name__ == "__main__":
    main()
