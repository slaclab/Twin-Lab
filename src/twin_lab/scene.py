"""Load, inspect, and visualize standard Drake model scenes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from pydrake.all import (
    AddMultibodyPlantSceneGraph,
    Diagram,
    DiagramBuilder,
    MultibodyPlant,
    Parser,
    QueryObject,
    SceneGraph,
)

from .paths import REPOSITORY_ROOT

PACKAGE_XML = REPOSITORY_ROOT / "package.xml"


@dataclass(frozen=True)
class SignedDistanceReport:
    """Signed clearance between a pair of named collision geometries."""

    a: str
    b: str
    distance_m: float


@dataclass
class DrakeScene:
    """A parsed Model Directives scene ready for kinematic queries."""

    diagram: Diagram
    plant: MultibodyPlant
    scene_graph: SceneGraph

    def create_context(self):
        return self.diagram.CreateDefaultContext()

    def set_joint_positions(self, root_context, positions: Mapping[str, float]) -> None:
        """Set scalar joints using scoped names such as ``stage_left::x``."""

        plant_context = self.plant.GetMyMutableContextFromRoot(root_context)
        for scoped_name, value in positions.items():
            model_name, separator, joint_name = scoped_name.partition("::")
            if not separator:
                raise ValueError(f"Joint name '{scoped_name}' must be scoped as MODEL::JOINT")
            model_instance = self.plant.GetModelInstanceByName(model_name)
            joint = self.plant.GetJointByName(joint_name, model_instance)
            if joint.num_positions() != 1:
                raise ValueError(f"Joint '{scoped_name}' is not a scalar joint")
            lower = float(joint.position_lower_limits()[0])
            upper = float(joint.position_upper_limits()[0])
            if not lower <= value <= upper:
                raise ValueError(
                    f"Joint '{scoped_name}' value {value} is outside [{lower}, {upper}]"
                )
            start = joint.position_start()
            positions_vector = self.plant.GetPositions(plant_context).copy()
            positions_vector[start] = value
            self.plant.SetPositions(plant_context, positions_vector)

    def signed_distances(
        self, root_context, *, max_distance_m: float
    ) -> list[SignedDistanceReport]:
        """Return candidate geometry pairs within the requested distance."""

        scene_context = self.scene_graph.GetMyContextFromRoot(root_context)
        query = cast(QueryObject, self.scene_graph.get_query_output_port().Eval(scene_context))
        inspector = query.inspector()
        pairs = query.ComputeSignedDistancePairwiseClosestPoints(max_distance_m)
        reports = [
            SignedDistanceReport(
                a=self._geometry_name(inspector, pair.id_A),
                b=self._geometry_name(inspector, pair.id_B),
                distance_m=float(pair.distance),
            )
            for pair in pairs
        ]
        return sorted(reports, key=lambda item: (item.distance_m, item.a, item.b))

    def _geometry_name(self, inspector, geometry_id) -> str:
        frame_id = inspector.GetFrameId(geometry_id)
        body = self.plant.GetBodyFromFrameId(frame_id)
        model_name = self.plant.GetModelInstanceName(body.model_instance())
        return f"{model_name}::{body.name()}::{inspector.GetName(geometry_id)}"


def load_scene(path: str | Path, *, meshcat=None) -> DrakeScene:
    """Parse an SDF, URDF, or Drake Model Directives file."""

    model_path = Path(path).resolve()
    builder = DiagramBuilder()
    plant, scene_graph = AddMultibodyPlantSceneGraph(builder, time_step=0.0)
    parser = Parser(plant, scene_graph)
    parser.package_map().AddPackageXml(PACKAGE_XML)
    parser.AddModels(model_path)
    plant.Finalize()
    if meshcat is not None:
        from pydrake.geometry import MeshcatVisualizer, MeshcatVisualizerParams, Role

        # Illustration only: the proximity role would draw every convex hull as wireframe.
        MeshcatVisualizer.AddToBuilder(
            builder, scene_graph, meshcat, MeshcatVisualizerParams(role=Role.kIllustration)
        )
    return DrakeScene(
        diagram=builder.Build(),
        plant=plant,
        scene_graph=scene_graph,
    )


def main() -> None:
    """Open a standard model file in Drake's browser-based ModelVisualizer."""

    import argparse

    # pydrake's stub omits ModelVisualizer, which exists at runtime.
    from pydrake.visualization import ModelVisualizer  # pyright: ignore[reportAttributeAccessIssue]

    parser = argparse.ArgumentParser(description="View an SDF, URDF, or Drake scene")
    parser.add_argument("model_file")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Publish once and exit (useful for automated smoke tests)",
    )
    args = parser.parse_args()

    visualizer = ModelVisualizer(visualize_frames=True)
    visualizer.package_map().AddPackageXml(PACKAGE_XML)
    visualizer.AddModels(Path(args.model_file).resolve())
    print(f"Meshcat: {visualizer.meshcat().web_url()}")
    visualizer.Run(loop_once=args.once)


if __name__ == "__main__":
    main()
