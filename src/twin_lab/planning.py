"""Planning-oriented Drake model loading.

This module is the boundary between Twin-Lab model files and Drake's planning
algorithms.  Keep it separate from the interactive scene loader so the
planning diagram can gain planner-specific configuration without changing the
viewer contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydrake.planning import RobotDiagramBuilder, SceneGraphCollisionChecker
from pydrake.multibody.tree import ModelInstanceIndex

from .scene import PACKAGE_XML


@dataclass(frozen=True)
class PlanningDiagram:
    """A finalized Drake robot diagram and the model instances it can plan."""

    robot_diagram: object
    robot_model_instances: tuple[int, ...]

    @property
    def plant(self):
        return self.robot_diagram.plant()

    @property
    def scene_graph(self):
        return self.robot_diagram.scene_graph()


def load_planning_diagram(
    path: str | Path,
    *,
    robot_model_instances: tuple[str, ...] | None = None,
) -> PlanningDiagram:
    """Load a model file into Drake's planning diagram.

    ``robot_model_instances`` names the movable model instances that planners
    should treat as robot configuration.  If omitted, every non-world model
    instance is selected, which is useful for fixtures and early integration
    tests.  Production callers should pass an explicit planning group.
    """

    model_path = Path(path).resolve()
    builder = RobotDiagramBuilder(time_step=0.0)
    builder.parser().package_map().AddPackageXml(PACKAGE_XML)
    builder.parser().AddModels(model_path)
    robot_diagram = builder.Build()
    plant = robot_diagram.plant()

    if robot_model_instances is None:
        names = [
            plant.GetModelInstanceName(ModelInstanceIndex(index))
            for index in range(plant.num_model_instances())
            if plant.GetModelInstanceName(ModelInstanceIndex(index)) not in {"world", "default"}
        ]
    else:
        names = list(robot_model_instances)

    missing = [name for name in names if not plant.HasModelInstanceNamed(name)]
    if missing:
        raise ValueError(f"Unknown planning model instance(s): {', '.join(missing)}")

    return PlanningDiagram(
        robot_diagram=robot_diagram,
        robot_model_instances=tuple(plant.GetModelInstanceByName(name) for name in names),
    )


def make_collision_checker(
    planning: PlanningDiagram,
    *,
    env_collision_padding: float = 0.0,
    self_collision_padding: float = 0.0,
    edge_step_size: float = 0.01,
) -> SceneGraphCollisionChecker:
    """Create Drake's native configuration and edge collision checker."""

    return SceneGraphCollisionChecker(
        model=planning.robot_diagram,
        robot_model_instances=list(planning.robot_model_instances),
        env_collision_padding=env_collision_padding,
        self_collision_padding=self_collision_padding,
        edge_step_size=edge_step_size,
    )