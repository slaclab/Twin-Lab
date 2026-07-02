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
    "detect_interferences",
    "place_bodies",
]
