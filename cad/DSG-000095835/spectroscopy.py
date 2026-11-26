"""Bind the 95835 cylindrical analyzers and chip face to the Drake motion model."""

import json
import math
from collections.abc import Mapping, Sequence

import numpy as np
from controls import AssemblySliderJoint, with_followers
from pydrake.systems.framework import Context

from twin_lab.scene import DrakeScene
from twin_lab.spectroscopy import (
    REFLECTIONS,
    Aperture,
    CrystalTrace,
    Detector,
    bragg_angle,
    cylinder_aperture,
    trace_crystal,
)
from twin_lab.spectroscopy_align import AlignmentAxis, AlignmentRig

MODEL = "DSG-000095835"
PREFIX = f"{MODEL}::"
IP_M = np.zeros(3)
CHIP = "REF__Chip__sa39154207"
CRYSTAL = "REF__XRStech__CylinderCrystalAnalyzer_XPP_L2SI"
DETECTOR_X = "epix100_x_joint"
COMMON_AXES = (
    "parker_lift_joint", "parker_cross_joint", "analyzer_rotation_joint",
    DETECTOR_X, "epix100_y_joint", "epix100_z_joint", "epix100_tilt_joint",
)
CRYSTAL_AXES = tuple(
    tuple(f"crystal_{i}_{axis}_joint" for axis in ("translation", "rotation", "tilt"))
    for i in range(1, 5)
)
AXES = (*COMMON_AXES, *(name for group in CRYSTAL_AXES for name in group))


def alignment_rig(
    joints: Sequence[AssemblySliderJoint],
    followers: Mapping[str, tuple[str, Mapping]],
    *,
    scene: DrakeScene | None = None,
) -> AlignmentRig[Context]:
    by_name = {joint.joint_name: joint for joint in joints}

    def axis(name: str) -> AlignmentAxis:
        joint = by_name[name]
        lower, upper, _ = joint.spectroscopy_bounds()
        return AlignmentAxis(
            PREFIX + name, joint.label, lower, upper,
            lambda value: (value + joint.logical_offset) * joint.scale,
            lambda value: min(max(joint.to_sdf(value), joint.sdf_lower), joint.sdf_upper),
        )

    def set_positions(context: Context, positions: Mapping[str, float]) -> None:
        if scene is None:
            raise RuntimeError("Alignment requires a loaded Drake scene")
        scene.set_joint_positions(context, with_followers(positions, followers, prefix=PREFIX))

    return AlignmentRig(
        tuple(map(axis, COMMON_AXES)),
        tuple(tuple(map(axis, group)) for group in CRYSTAL_AXES),
        set_positions, Context.Clone, PREFIX + DETECTOR_X,
    )


def load_apertures() -> tuple[list[Aperture], Detector]:
    """Resolve the optics on their reviewed moving bodies, not the alternate assemblies."""
    import yaml
    from build import CACHE, HERE, RECIPE, read_shape
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepGProp import BRepGProp
    from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    review = yaml.safe_load(RECIPE.read_text())
    stats = json.loads((CACHE / "stats.json").read_text())
    names = {
        row["ref"]: row["name"].split("_oa_")[0]
        for row in json.loads((HERE / "manifest.json").read_text())["occurrences"]
    }

    def surfaces(body: str, name: str):
        parts = review["bodies"][body]["parts"]
        refs = [part for part in parts if isinstance(part, str) and names[part] == name]
        if len(refs) != 1:
            raise ValueError(f"{body}: expected exactly one reviewed CAD part named {name}")
        explorer = TopExp_Explorer(read_shape(refs[0], review, stats), TopAbs_FACE)
        while explorer.More():
            face = TopoDS.Face_s(explorer.Current())
            props = GProp_GProps()
            BRepGProp.SurfaceProperties_s(face, props)
            sign = -1 if face.Orientation() == TopAbs_REVERSED else 1
            yield BRepAdaptor_Surface(face), props, sign
            explorer.Next()

    apertures = []
    for index in range(1, 5):
        candidates = [
            surface for surface, props, sign in surfaces(f"crystal_{index}_tilt", CRYSTAL)
            if surface.GetType() == GeomAbs_Cylinder and sign == -1 and props.Mass() > 1000
        ]
        if len(candidates) != 1:
            raise ValueError(f"Crystal {index}: expected one large concave cylindrical face")
        surface = candidates[0]
        cylinder = surface.Cylinder()
        apertures.append(cylinder_aperture(
            np.array(cylinder.Location().Coord()) / 1000,
            np.array([
                cylinder.XAxis().Direction().Coord(),
                cylinder.YAxis().Direction().Coord(),
                cylinder.Axis().Direction().Coord(),
            ]),
            cylinder.Radius() / 1000,
            (
                surface.FirstUParameter(), surface.LastUParameter(),
                surface.FirstVParameter() / 1000, surface.LastVParameter() / 1000,
            ),
        ))
    candidates = []
    for surface, props, sign in surfaces("epix100_tilt", CHIP):
        if surface.GetType() != GeomAbs_Plane or props.Mass() < 1000:
            continue
        normal = sign * np.array(surface.Plane().Axis().Direction().Coord())
        if normal[2] > 0.9:
            candidates.append((np.array(props.CentreOfMass().Coord()) / 1000, normal))
    if len(candidates) != 1:
        raise ValueError("ePix100: expected one upward-facing chip surface")
    center, normal = candidates[0]
    u = np.array([1.0, 0.0, 0.0]) - normal[0] * normal
    u /= np.linalg.norm(u)
    return apertures, Detector(center, u, np.cross(normal, u), normal)


class Spectrometer:
    crystal_labels = ("1", "2", "3", "4")
    reflections = REFLECTIONS
    shortlist_angle_deg = 79.0  # Near the demonstrated 250 mm Fe and Co setups.

    def __init__(self, scene: DrakeScene, context: Context):
        self.apertures, self.detector = load_apertures()
        self.plant = scene.plant
        model = self.plant.GetModelInstanceByName(MODEL)
        analyzer_bodies = [f"crystal_{number}_tilt" for number in self.crystal_labels]
        self.bodies = [
            self.plant.GetBodyByName(name, model) for name in [*analyzer_bodies, "epix100_tilt"]
        ]
        self.home = [pose.inverse() for pose in self._poses(context)]

    def _poses(self, context: Context):
        plant_context = self.plant.GetMyContextFromRoot(context)
        return [body.EvalPoseInWorld(plant_context) for body in self.bodies]

    def trace(
        self, context: Context, energy_ev: float, spacing_a: float, order: int,
        half_width_deg: float, *, crystals: Sequence[int] | None = None, aim: bool = False,
    ) -> tuple[float | None, Detector, list[CrystalTrace]]:
        theta = bragg_angle(energy_ev, spacing_a, order)
        if not (math.isfinite(half_width_deg) and 0 < half_width_deg < 90):
            raise ValueError("Bragg half-width must be between 0 and 90 degrees")
        relative = [
            (pose @ home).GetAsMatrix4()
            for pose, home in zip(self._poses(context), self.home, strict=True)
        ]
        detector = self.detector.moved(relative[-1])
        indices = range(len(self.crystal_labels)) if crystals is None else crystals
        traces = [
            trace_crystal(
                IP_M, self.apertures[index], relative[index], detector, theta,
                math.radians(half_width_deg), aim=aim,
            )
            for index in indices
        ]
        return theta, detector, traces
