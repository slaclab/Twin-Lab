"""Engineer-facing clearance reporting for a compiled stage assembly.

Drake already filters geometry pairs that share a body, sit either side of one
joint, or are welded into the same rigid subgraph. Everything left over is a
pair that the reviewed CAD says can genuinely approach, so a nonzero count at
the home pose is a finding rather than noise.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

from .paths import resolve_repo_path
from .scene import DrakeScene, load_scene

PART_PATTERN = re.compile(r"(?<![0-9A-Za-z])([AP]\d{3,4})(?![0-9A-Za-z])", re.IGNORECASE)


@dataclass(frozen=True)
class Clearance:
    """Signed distance between two collision geometries at one pose."""

    a: str
    b: str
    distance_m: float

    @property
    def parts(self) -> tuple[str, str]:
        return (_part_of(self.a), _part_of(self.b))

    @property
    def names(self) -> tuple[str, str]:
        return (_short(self.a), _short(self.b))


@dataclass(frozen=True)
class ClearanceReport:
    """Sorted clearances at one pose, split by an engineering warning band."""

    clearances: tuple[Clearance, ...]
    warn_m: float

    @property
    def touching(self) -> tuple[Clearance, ...]:
        return tuple(item for item in self.clearances if item.distance_m <= 0.0)

    @property
    def warnings(self) -> tuple[Clearance, ...]:
        return tuple(item for item in self.clearances if 0.0 < item.distance_m <= self.warn_m)

    @property
    def worst_m(self) -> float | None:
        return self.clearances[0].distance_m if self.clearances else None

    def summary(self) -> str:
        if not self.clearances:
            return f"clear: nothing within {self.warn_m * 1000:.0f} mm"
        worst = self.clearances[0]
        state = "TOUCHING" if worst.distance_m <= 0.0 else "close"
        return (
            f"{state}: {worst.distance_m * 1000:+.2f} mm "
            f"{_short(worst.a)} <-> {_short(worst.b)} "
            f"({len(self.touching)} touching, {len(self.warnings)} within "
            f"{self.warn_m * 1000:.0f} mm)"
        )


class CollisionModel:
    """A compiled SDF assembly with reviewed filters applied, ready for clearance queries."""

    def __init__(self, scene: DrakeScene, ignored_pairs: frozenset[tuple[str, str]] = frozenset()):
        self.scene = scene
        self.ignored_pairs = ignored_pairs
        self.context = scene.create_context()

    @classmethod
    def load(
        cls, sdf_path: str | Path, *, ignore_file: str | Path | None = None
    ) -> CollisionModel:
        scene = load_scene(sdf_path)
        ignored = read_ignored_pairs(ignore_file) if ignore_file is not None else frozenset()
        return cls(scene, ignored)

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
            Clearance(a=item.a, b=item.b, distance_m=item.distance_m)
            for item in distances
            if _pair_key(item.a, item.b) not in self.ignored_pairs
        )
        return ClearanceReport(clearances=clearances, warn_m=warn_m)


def read_ignored_pairs(path: str | Path) -> frozenset[tuple[str, str]]:
    """Read reviewed part pairs that are permanently in contact by design."""

    data = yaml.safe_load(resolve_repo_path(path).read_text(encoding="utf-8")) or {}
    pairs = set()
    for entry in data.get("ignored_pairs", []):
        first, second = (str(value) for value in entry["pair"])
        pairs.add(tuple(sorted((first.upper(), second.upper()))))
    return frozenset(pairs)


def _pair_key(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((_part_of(a), _part_of(b))))


def _part_of(geometry_name: str) -> str:
    """Recover the reviewed occurrence reference baked into a collision geometry name."""

    matches = PART_PATTERN.findall(geometry_name)
    return matches[-1].upper() if matches else geometry_name.rsplit("::", 1)[-1]


def _short(geometry_name: str) -> str:
    """Name a geometry by its owning link and reviewed part reference."""

    segments = geometry_name.split("::")
    link = segments[1] if len(segments) > 2 else segments[0]
    return f"{link}/{_part_of(geometry_name)}"
