"""Engineer-facing clearance reporting for a compiled stage assembly.

Drake already filters geometry pairs that share a body, sit either side of one
joint, or are welded into the same rigid subgraph. Everything left over is a
pair that the reviewed CAD says can genuinely approach, so a nonzero count at
the home pose is a finding rather than noise.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
import yaml

from .clearance_refine import ClearanceRefiner, Refinement
from .paths import resolve_repo_path
from .scene import DrakeScene, load_scene

PART_PATTERN = re.compile(r"(?<![0-9A-Za-z])([AP]\d{3,4})(?![0-9A-Za-z])", re.IGNORECASE)
# Compiled joint names carry the stage they drive, e.g. ``middle_crystal_a044_motion``.
STAGE_PATTERN = re.compile(r"(?<![0-9A-Za-z])(A\d{3,4})(?![0-9A-Za-z])", re.IGNORECASE)


@dataclass(frozen=True)
class Clearance:
    """Signed distance between two collision geometries at one pose."""

    a: str
    b: str
    distance_m: float
    # Where on the two hulls the distance was measured, and how those hulls sit in the
    # world. Both are needed to re-check the pair against the CAD; see clearance_refine.
    witness_a_m: np.ndarray | None = field(default=None, compare=False)
    witness_b_m: np.ndarray | None = field(default=None, compare=False)
    pose_a: np.ndarray | None = field(default=None, compare=False)
    pose_b: np.ndarray | None = field(default=None, compare=False)

    @property
    def parts(self) -> tuple[str, str]:
        return (part_of(self.a), part_of(self.b))

    @property
    def names(self) -> tuple[str, str]:
        return (_short(self.a), _short(self.b))


@dataclass(frozen=True)
class ClearanceReport:
    """Sorted clearances at one pose, split by an engineering warning band."""

    clearances: tuple[Clearance, ...]
    warn_m: float
    part_labels: Mapping[str, str] = field(default_factory=dict)

    def label(self, ref: str) -> str:
        """The part's Teamcenter number, or the reviewed ref when the CAD gives no number."""

        return self.part_labels.get(ref, ref)

    def labeled_parts(self, clearance: Clearance) -> tuple[str, str]:
        first, second = clearance.parts
        return (self.label(first), self.label(second))

    def described(self, clearance: Clearance) -> tuple[str, str]:
        return (_short(clearance.a, self.part_labels), _short(clearance.b, self.part_labels))

    @property
    def touching(self) -> tuple[Clearance, ...]:
        return tuple(item for item in self.clearances if item.distance_m <= 0.0)

    @property
    def warnings(self) -> tuple[Clearance, ...]:
        return tuple(item for item in self.clearances if 0.0 < item.distance_m <= self.warn_m)

    @property
    def touching_pairs(self) -> tuple[tuple[str, str], ...]:
        """Distinct part pairs in contact.

        One part carries dozens of hulls, so a raw clearance count says nothing about how
        many interfaces there are to look at.
        """

        return tuple(dict.fromkeys(item.parts for item in self.touching))

    @property
    def warning_pairs(self) -> tuple[tuple[str, str], ...]:
        """Distinct part pairs inside the band that are not already in contact."""

        touching = set(self.touching_pairs)
        return tuple(
            pair
            for pair in dict.fromkeys(item.parts for item in self.warnings)
            if pair not in touching
        )

    @property
    def interference(self) -> bool:
        """True when any reviewed pair is in contact or penetrating at this pose."""

        return bool(self.touching)

    @property
    def status(self) -> str:
        """``interference`` when touching, ``close`` when inside the band, else ``clear``."""

        if self.touching:
            return "interference"
        return "close" if self.warnings else "clear"

    def corrected(self, refinements: Iterable[Refinement]) -> ClearanceReport:
        """A copy with the CAD re-check applied, and only ever in the clearing direction.

        A hull encloses the part it stands in for, so a hull distance can only understate
        the gap. Taking the larger of the two therefore keeps the report a superset of the
        real interferences: a re-check can drop a pair out of the band, never add one.
        """

        corrections = {
            tuple(sorted(ref.parts)): ref.verified_m
            for ref in refinements
            if ref.verified_m is not None
        }
        if not corrections:
            return self
        kept = []
        for item in self.clearances:
            verified = corrections.get(tuple(sorted(part.upper() for part in item.parts)))
            if verified is None or verified <= item.distance_m:
                kept.append(item)
            elif verified <= self.warn_m:
                kept.append(replace(item, distance_m=verified))
        kept.sort(key=lambda item: (item.distance_m, item.a, item.b))
        return replace(self, clearances=tuple(kept))

    def offenders(self, limit: int = 3) -> tuple[Clearance, ...]:
        """Worst clearance per part pair, so one physical interface is reported once."""

        worst_by_pair: dict[tuple[str, str], Clearance] = {}
        for item in self.clearances:
            worst_by_pair.setdefault(item.parts, item)
        return tuple(worst_by_pair.values())[:limit]

    def geometry_states(self) -> dict[str, str]:
        """Map each offending collision geometry to ``interference`` or ``close``, worst first.

        A geometry can appear in several pairs, and contact outranks a near miss.
        """

        states: dict[str, str] = {}
        for item in self.clearances:
            if item.distance_m > self.warn_m:
                continue
            state = "interference" if item.distance_m <= 0.0 else "close"
            for name in (item.a, item.b):
                if states.get(name) != "interference":
                    states[name] = state
        return states

    @property
    def worst_m(self) -> float | None:
        return self.clearances[0].distance_m if self.clearances else None

    def summary(self) -> str:
        if not self.clearances:
            return f"clear: nothing within {self.warn_m * 1000:.0f} mm"
        worst = self.clearances[0]
        state = "TOUCHING" if worst.distance_m <= 0.0 else "close"
        first, second = self.described(worst)
        return (
            f"{state}: {worst.distance_m * 1000:+.2f} mm "
            f"{first} <-> {second} "
            f"({len(self.touching_pairs)} part pairs touching, "
            f"{len(self.warning_pairs)} more within {self.warn_m * 1000:.0f} mm)"
        )


class CollisionModel:
    """A compiled SDF assembly with reviewed filters applied, ready for clearance queries."""

    def __init__(
        self,
        scene: DrakeScene,
        ignored_pairs: frozenset[tuple[str, str]] = frozenset(),
        part_labels: Mapping[str, str] | None = None,
        decomposition_dir: str | Path | None = None,
    ):
        self.scene = scene
        self.ignored_pairs = ignored_pairs
        self.part_labels = dict(part_labels or {})
        self.context = scene.create_context()
        self.reopened_joints = self._reopen_anchored_pairs()
        self.refiner = (
            ClearanceRefiner(decomposition_dir) if decomposition_dir is not None else None
        )

    def _reopen_anchored_pairs(self) -> int:
        """Restore clearance checking between each stage's first moving link and the room.

        Drake filters the two bodies either side of a joint. The compiled assembly holds
        the whole static environment in a single anchored body, so that filter also hides
        every approach between a stage's first moving link and the chamber, the enclosure,
        or a neighbouring stage. Only the driven stage's own fixed-role geometry is truly
        adjacent, so that alone stays filtered.

        Returns the number of joints whose surroundings were reopened.
        """

        from pydrake.geometry import CollisionFilterDeclaration, GeometrySet, Role
        from pydrake.multibody.tree import JointIndex

        plant = self.scene.plant
        scene_graph = self.scene.scene_graph
        inspector = scene_graph.model_inspector()
        anchored = {body.name() for body in plant.GetBodiesWeldedTo(plant.world_body())}

        def proximity(body) -> list:
            frame_id = plant.GetBodyFrameIdOrThrow(body.index())
            return list(inspector.GetGeometries(frame_id, Role.kProximity))

        declaration = CollisionFilterDeclaration()
        reopened = 0
        for index in range(plant.num_joints()):
            joint = plant.get_joint(JointIndex(index))
            if joint.num_positions() == 0 or joint.parent_body().name() not in anchored:
                continue
            stage = STAGE_PATTERN.search(joint.name())
            if stage is None:
                continue
            own_stage = f"{stage.group(1).lower()}_fixed"
            moving = proximity(joint.child_body())
            surroundings = [
                geometry_id
                for geometry_id in proximity(joint.parent_body())
                if not _leaf(inspector.GetName(geometry_id)).startswith(own_stage)
            ]
            if not moving or not surroundings:
                continue
            declaration.AllowBetween(GeometrySet(moving), GeometrySet(surroundings))
            reopened += 1
        if reopened:
            scene_context = scene_graph.GetMyContextFromRoot(self.context)
            scene_graph.collision_filter_manager(scene_context).Apply(declaration)
        return reopened

    @classmethod
    def load(
        cls,
        sdf_path: str | Path,
        *,
        ignore_file: str | Path | None = None,
        label_source: str | Path | None = None,
        decomposition_dir: str | Path | None = None,
    ) -> CollisionModel:
        scene = load_scene(sdf_path)
        ignored = read_ignored_pairs(ignore_file) if ignore_file is not None else frozenset()
        labels = read_part_labels(label_source) if label_source is not None else {}
        return cls(scene, ignored, labels, decomposition_dir)

    def joint_names(self) -> list[str]:
        from pydrake.multibody.tree import JointIndex

        plant = self.scene.plant
        return [
            plant.get_joint(JointIndex(index)).name()
            for index in range(plant.num_joints())
            if plant.get_joint(JointIndex(index)).num_positions() == 1
        ]

    def set_positions(self, positions: Mapping[str, float]) -> None:
        """Set scalar joints by unscoped SDF joint name, clamped to the reviewed limits."""

        plant = self.scene.plant
        plant_context = plant.GetMyMutableContextFromRoot(self.context)
        values = plant.GetPositions(plant_context).copy()
        for name, value in positions.items():
            joint = plant.GetJointByName(name)
            lower = float(joint.position_lower_limits()[0])
            upper = float(joint.position_upper_limits()[0])
            values[joint.position_start()] = min(max(float(value), lower), upper)
        plant.SetPositions(plant_context, values)

    def report(
        self, *, warn_m: float = 0.005, max_distance_m: float | None = None
    ) -> ClearanceReport:
        distances = self.scene.signed_distances(
            self.context, max_distance_m=max_distance_m if max_distance_m is not None else warn_m
        )
        clearances = tuple(
            Clearance(
                a=item.a,
                b=item.b,
                distance_m=item.distance_m,
                witness_a_m=item.witness_a_m,
                witness_b_m=item.witness_b_m,
                pose_a=item.pose_a,
                pose_b=item.pose_b,
            )
            for item in distances
            if _pair_key(item.a, item.b) not in self.ignored_pairs
        )
        return ClearanceReport(clearances=clearances, warn_m=warn_m, part_labels=self.part_labels)

    def refine(
        self, report: ClearanceReport, *, limit: int = 12, with_mesh: bool = True
    ) -> tuple[Refinement, ...]:
        """Re-check the reported pairs against the CAD behind the hulls, worst first.

        Every pair inside the band is checked, not only the ones already in contact: the
        same hull proudness that turns a clear pair into a contact turns a clear pair into
        a near miss, and both readings mislead the reviewer.
        """

        if self.refiner is None:
            return ()
        seen: set[tuple[str, str]] = set()
        refinements = []
        for clearance in report.clearances:
            if clearance.parts in seen:
                continue
            seen.add(clearance.parts)
            refinements.append(self.refiner.refine(clearance, with_mesh=with_mesh))
            if len(refinements) >= limit:
                break
        return tuple(refinements)

    def verify(
        self, report: ClearanceReport, *, limit: int = 12, with_mesh: bool = True
    ) -> tuple[ClearanceReport, tuple[Refinement, ...]]:
        """The report with the CAD re-check folded in, alongside the evidence for it.

        ``with_mesh`` false keeps only the proudness correction, which is a table lookup;
        measuring the tessellated parts themselves costs tens of milliseconds a pair.
        """

        refinements = self.refine(report, limit=limit, with_mesh=with_mesh)
        return report.corrected(refinements), refinements


def read_ignored_pairs(path: str | Path) -> frozenset[tuple[str, str]]:
    """Read reviewed part pairs that are permanently in contact by design."""

    data = yaml.safe_load(resolve_repo_path(path).read_text(encoding="utf-8")) or {}
    pairs = set()
    for entry in data.get("ignored_pairs", []):
        first, second = (str(value) for value in entry["pair"])
        pairs.add(tuple(sorted((first.upper(), second.upper()))))
    return frozenset(pairs)


def read_part_labels(inventory_path: str | Path) -> dict[str, str]:
    """Map each reviewed occurrence ref to its Teamcenter number, read from the CAD manifest."""

    inventory_file = resolve_repo_path(inventory_path)
    inventory = yaml.safe_load(inventory_file.read_text(encoding="utf-8")) or {}
    manifest_ref = inventory.get("cad_manifest")
    if not manifest_ref:
        return {}
    manifest_path = resolve_repo_path(manifest_ref, relative_to=inventory_file.parent)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    labels: dict[str, str] = {}
    for occurrence in manifest.get("occurrences", []):
        ref = occurrence.get("ref")
        teamcenter = _teamcenter_id(occurrence.get("name", ""))
        if ref and teamcenter:
            labels[str(ref).upper()] = teamcenter
    return labels


def _pair_key(a: str, b: str) -> tuple[str, str]:
    first, second = sorted((part_of(a), part_of(b)))
    return first, second


def _leaf(scoped_name: str) -> str:
    return scoped_name.rsplit("::", 1)[-1].lower()


def part_of(geometry_name: str) -> str:
    """Recover the reviewed occurrence reference baked into a collision geometry name."""

    matches = PART_PATTERN.findall(geometry_name)
    return matches[-1].upper() if matches else geometry_name.rsplit("::", 1)[-1]


_TEAMCENTER_PATTERN = re.compile(r"^[A-Z]{2,}[0-9]*-[0-9]+")


def _teamcenter_id(name: str) -> str | None:
    """Reviewed CAD names lead with a Teamcenter number; fasteners carry a shape description."""

    match = _TEAMCENTER_PATTERN.match(name.strip())
    return match.group(0) if match else None


def _short(geometry_name: str, labels: Mapping[str, str] | None = None) -> str:
    """Name a geometry by its owning link and reviewed part, as a Teamcenter number when known."""

    segments = geometry_name.split("::")
    link = segments[1] if len(segments) > 2 else segments[0]
    ref = part_of(geometry_name)
    return f"{link}/{labels.get(ref, ref) if labels else ref}"
