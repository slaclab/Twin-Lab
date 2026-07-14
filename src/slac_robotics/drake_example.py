"""Minimal Drake collision example for WSL/Python validation.

Run with:
    python -m slac_robotics.drake_example
"""

from __future__ import annotations

from pydrake.all import (
    AddMultibodyPlantSceneGraph,
    Box,
    CoulombFriction,
    DiagramBuilder,
    RigidTransform,
    SpatialInertia,
    UnitInertia,
)


def run_demo() -> tuple[int, int]:
    """Return (overlap_count, separated_count) for two moving boxes."""
    builder = DiagramBuilder()
    plant, scene_graph = AddMultibodyPlantSceneGraph(builder, time_step=0.0)

    inertia = SpatialInertia(
        mass=1.0,
        p_PScm_E=[0.0, 0.0, 0.0],
        G_SP_E=UnitInertia.SolidBox(0.2, 0.2, 0.2),
    )

    body_a = plant.AddRigidBody("body_a", inertia)
    body_b = plant.AddRigidBody("body_b", inertia)

    friction = CoulombFriction(static_friction=0.9, dynamic_friction=0.8)
    plant.RegisterCollisionGeometry(body_a, RigidTransform(), Box(0.2, 0.2, 0.2), "a_col", friction)
    plant.RegisterCollisionGeometry(body_b, RigidTransform(), Box(0.2, 0.2, 0.2), "b_col", friction)

    plant.Finalize()
    diagram = builder.Build()
    context = diagram.CreateDefaultContext()
    plant_context = plant.GetMyMutableContextFromRoot(context)
    scene_graph_context = scene_graph.GetMyMutableContextFromRoot(context)

    plant.SetFreeBodyPose(plant_context, body_a, RigidTransform([0.0, 0.0, 0.0]))
    plant.SetFreeBodyPose(plant_context, body_b, RigidTransform([0.15, 0.0, 0.0]))
    overlap_count = len(
        scene_graph.get_query_output_port().Eval(scene_graph_context).ComputePointPairPenetration()
    )

    plant.SetFreeBodyPose(plant_context, body_b, RigidTransform([0.50, 0.0, 0.0]))
    separated_count = len(
        scene_graph.get_query_output_port().Eval(scene_graph_context).ComputePointPairPenetration()
    )

    return overlap_count, separated_count


def main() -> None:
    overlap_count, separated_count = run_demo()
    print(f"overlap_count: {overlap_count}")
    print(f"separated_count: {separated_count}")


if __name__ == "__main__":
    main()
