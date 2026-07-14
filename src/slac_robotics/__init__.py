"""SLAC Robotics Framework."""

__version__ = "0.1.0"
__author__ = "SLAC"

from .collision import CollisionReport, PlacedBody, detect_interferences, place_bodies
from .model import (
    Body,
    BoxGeometry,
    Joint,
    JointKind,
    Stage,
    StageLimit,
    StageStack,
    SpectrometerModel,
    collision_pair,
)
from .step_io import MeshCollisionReport, detect_mesh_interferences, detect_step_interferences, load_step_mesh

__all__ = [
    "Body",
    "BoxGeometry",
    "CollisionReport",
    "Joint",
    "JointKind",
    "PlacedBody",
    "Stage",
    "StageLimit",
    "StageStack",
    "SpectrometerModel",
    "collision_pair",
    "MeshCollisionReport",
    "detect_mesh_interferences",
    "detect_step_interferences",
    "detect_interferences",
    "load_step_mesh",
    "place_bodies",
]
