"""Use the shared clearance UI with explicit bearings and source-CAD gap checks."""

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import yaml
from controls import read_controls
from OCP.BRep import BRep_Builder
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.gp import gp_Trsf
from OCP.TopoDS import TopoDS_Compound
from pydrake.geometry import CollisionFilterDeclaration, GeometrySet, Role

from twin_lab import collision_viewer
from twin_lab.collision import CollisionModel, part_of

RECIPE = Path(__file__).resolve().parent / "reviews" / "assembly.yaml"


class AssemblyCollisionModel(CollisionModel):
    """Restore adjacent-link checks without relying on legacy A-ref name patterns."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cad_shapes = {}
        self._cad_gaps = {}

    def _cad_shape(self, name):
        from build import CACHE, read_shape

        if name not in self._cad_shapes:
            review = yaml.safe_load(RECIPE.read_text())
            templates = yaml.safe_load((RECIPE.parent / review["split_templates"]).read_text())
            review["stage_splits"] = {
                ref: templates[key] for ref, key in review["stage_splits"].items()
            }
            stats = json.loads((CACHE / "stats.json").read_text())
            body, ref = name.split("/")
            selections = [
                part for part in review["bodies"][body]["parts"]
                if (part if isinstance(part, str) else part["ref"]) == ref
            ]
            if not selections:
                raise ValueError(f"No reviewed CAD selection for {name}")
            shape = TopoDS_Compound()
            builder = BRep_Builder()
            builder.MakeCompound(shape)
            for part in selections:
                builder.Add(shape, read_shape(part, review, stats))
            self._cad_shapes[name] = shape
        return self._cad_shapes[name]

    def report(self, *, warn_m=0.005, max_distance_m=None):
        report = super().report(warn_m=warn_m, max_distance_m=max_distance_m)
        corrected = []
        for item in report.clearances:
            if item.pose_a is None or item.pose_b is None:
                corrected.append(item)
                continue
            poses = (item.pose_a, item.pose_b)
            pose_key = tuple(pose.tobytes() for pose in poses)
            cached = self._cad_gaps.get(item.names)
            if cached is None or cached[0] != pose_key:
                shapes = []
                for name, pose in zip(item.names, poses, strict=True):
                    matrix = np.array(pose[:3, :], copy=True)
                    matrix[:, 3] *= 1000.0
                    transform = gp_Trsf()
                    transform.SetValues(*matrix.flatten().tolist())
                    shapes.append(
                        BRepBuilderAPI_Transform(self._cad_shape(name), transform, True).Shape()
                    )
                distance = BRepExtrema_DistShapeShape(*shapes)
                gap = distance.Value() / 1000.0 if distance.IsDone() else 0.0
                self._cad_gaps[item.names] = (pose_key, gap)
            else:
                gap = cached[1]
            if gap > 1e-7:
                item = replace(item, distance_m=max(item.distance_m, gap))
            if item.distance_m <= (warn_m if max_distance_m is None else max_distance_m):
                corrected.append(item)
        corrected.sort(key=lambda item: (item.distance_m, item.a, item.b))
        return replace(report, clearances=tuple(corrected))

    def _reopen_joint_adjacent_pairs(self) -> int:
        plant = self.scene.plant
        graph = self.scene.scene_graph
        inspector = graph.model_inspector()
        declaration = CollisionFilterDeclaration()
        reopened = 0
        for spec in yaml.safe_load(RECIPE.read_text())["joints"]:
            joint = plant.GetJointByName(spec["name"])
            fixed_refs, moving_refs = spec["bearing_parts"]

            def partition(body, bearing_refs):
                frame = plant.GetBodyFrameIdOrThrow(body.index())
                own, rest = [], []
                for gid in inspector.GetGeometries(frame, Role.kProximity):
                    target = own if part_of(inspector.GetName(gid)) in bearing_refs else rest
                    target.append(gid)
                return own, rest

            rail, support = partition(joint.parent_body(), fixed_refs)
            carriage, payload = partition(joint.child_body(), moving_refs)
            allowed = False
            for first, second in ((rail + support, payload), (support, carriage)):
                if first and second:
                    declaration.AllowBetween(GeometrySet(first), GeometrySet(second))
                    allowed = True
            reopened += int(allowed)
        if reopened:
            context = graph.GetMyContextFromRoot(self.context)
            graph.collision_filter_manager(context).Apply(declaration)
        return reopened


def view(package: Path) -> None:
    # The shared UI has no model-factory argument. This temporary binding affects
    # only this local process; repository source and other assemblies are unchanged.
    original = collision_viewer.CollisionModel
    original_controls = collision_viewer.read_joint_metadata
    collision_viewer.CollisionModel = AssemblyCollisionModel
    collision_viewer.read_joint_metadata = read_controls
    try:
        collision_viewer.run_collision_viewer(package, label_source=RECIPE)
    finally:
        collision_viewer.CollisionModel = original
        collision_viewer.read_joint_metadata = original_controls
