"""Core kinematic data model for stage-stack instruments."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, FrozenSet, Iterable, List, Sequence, Tuple

Vec3 = Tuple[float, float, float]
CollisionPair = FrozenSet[str]


class JointKind(str, Enum):
    """Supported primitive joint motion types."""

    LINEAR = "linear"
    ROTARY = "rotary"
    GONIO = "gonio"


# Backward-compatible name for the first prototype API.
StageKind = JointKind


@dataclass(frozen=True)
class StageLimit:
    """Joint limits in SI units: meters for linear, radians for angular."""

    minimum: float
    maximum: float

    def contains(self, value: float) -> bool:
        return self.minimum <= value <= self.maximum


@dataclass(frozen=True)
class Joint:
    """One actuated degree of freedom in a stage stack."""

    name: str
    kind: JointKind
    axis: Vec3
    limit: StageLimit
    parent_offset: Vec3 = (0.0, 0.0, 0.0)
    home: float = 0.0


@dataclass(frozen=True)
class BoxGeometry:
    """Axis-aligned box geometry in a body's local frame."""

    size: Vec3
    local_offset: Vec3 = (0.0, 0.0, 0.0)


@dataclass(frozen=True)
class Body:
    """A physical collision body attached to a joint output frame."""

    name: str
    geometry: BoxGeometry


@dataclass(frozen=True)
class Stage:
    """A joint and the physical bodies that move with it."""

    joint: Joint
    bodies: Tuple[Body, ...]

    @classmethod
    def from_box(
        cls,
        *,
        name: str,
        kind: JointKind,
        axis: Vec3,
        limit: StageLimit,
        bbox_size: Vec3,
        mount_offset: Vec3 = (0.0, 0.0, 0.0),
        body_name: str | None = None,
        body_offset: Vec3 = (0.0, 0.0, 0.0),
        home: float = 0.0,
    ) -> "Stage":
        """Create a one-joint, one-box stage for early coarse models."""

        joint = Joint(
            name=name,
            kind=kind,
            axis=axis,
            limit=limit,
            parent_offset=mount_offset,
            home=home,
        )
        body = Body(
            name=body_name or f"{name}_body",
            geometry=BoxGeometry(size=bbox_size, local_offset=body_offset),
        )
        return cls(joint=joint, bodies=(body,))

    @property
    def name(self) -> str:
        return self.joint.name

    @property
    def kind(self) -> JointKind:
        return self.joint.kind

    @property
    def axis(self) -> Vec3:
        return self.joint.axis

    @property
    def limit(self) -> StageLimit:
        return self.joint.limit

    @property
    def mount_offset(self) -> Vec3:
        return self.joint.parent_offset

    @property
    def bbox_size(self) -> Vec3:
        if len(self.bodies) != 1:
            raise AttributeError("bbox_size is only defined for one-box stages")
        return self.bodies[0].geometry.size

    def body_names(self) -> List[str]:
        return [body.name for body in self.bodies]


@dataclass(frozen=True)
class StageStack:
    """An ordered parent-to-child chain of stages."""

    name: str
    stages: Sequence[Stage]
    base_offset: Vec3 = (0.0, 0.0, 0.0)

    def stage_names(self) -> List[str]:
        return [stage.name for stage in self.stages]

    def body_names(self) -> List[str]:
        return [body.name for stage in self.stages for body in stage.bodies]


def collision_pair(a: str, b: str) -> CollisionPair:
    """Create an order-independent collision-filter pair."""

    if a == b:
        raise ValueError("Collision filter pair must contain two different bodies")
    return frozenset((a, b))


@dataclass(frozen=True)
class SpectrometerModel:
    """Container for all stacks and world geometry."""

    stacks: Sequence[StageStack]
    # Chamber envelope (meters), centered at origin.
    chamber_size: Vec3
    collision_filters: FrozenSet[CollisionPair] = field(default_factory=frozenset)

    def all_stages(self) -> Iterable[Stage]:
        for stack in self.stacks:
            for stage in stack.stages:
                yield stage

    def all_joints(self) -> Iterable[Joint]:
        for stage in self.all_stages():
            yield stage.joint

    def all_bodies(self) -> Iterable[Body]:
        for stage in self.all_stages():
            yield from stage.bodies

    def is_collision_filtered(self, a: str, b: str) -> bool:
        return collision_pair(a, b) in self.collision_filters

    def validate_topology(self) -> None:
        """Raise ValueError for duplicate joint or body names."""

        joint_names = [joint.name for joint in self.all_joints()]
        body_names = [body.name for body in self.all_bodies()]
        duplicate_joints = _duplicates(joint_names)
        duplicate_bodies = _duplicates(body_names)

        if duplicate_joints:
            raise ValueError(f"Duplicate joint names: {', '.join(duplicate_joints)}")
        if duplicate_bodies:
            raise ValueError(f"Duplicate body names: {', '.join(duplicate_bodies)}")

    def validate_state(self, state: Dict[str, float]) -> None:
        """Raise ValueError if any joint value is missing, unknown, or out of limits."""

        self.validate_topology()
        joints = {joint.name: joint for joint in self.all_joints()}
        missing = sorted(set(joints) - set(state))
        unknown = sorted(set(state) - set(joints))

        if missing:
            raise ValueError(f"Missing state values: {', '.join(missing)}")
        if unknown:
            raise ValueError(f"Unknown state values: {', '.join(unknown)}")

        for joint_name, joint in joints.items():
            value = state[joint_name]
            if not joint.limit.contains(value):
                raise ValueError(
                    f"Joint '{joint_name}' value {value} is outside "
                    f"[{joint.limit.minimum}, {joint.limit.maximum}]"
                )


def _duplicates(names: Sequence[str]) -> List[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for name in names:
        if name in seen:
            duplicates.add(name)
        seen.add(name)
    return sorted(duplicates)
