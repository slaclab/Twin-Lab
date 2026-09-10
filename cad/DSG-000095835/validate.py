#!/usr/bin/env python3
"""Validate the local assembly's compiled CAD-frame kinematics in Drake."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from pydrake.multibody.tree import JointIndex, PrismaticJoint, RevoluteJoint

from twin_lab.scene import load_scene
from twin_lab.sdf_compiler import _safe_name

ASSEMBLY_DIR = Path(__file__).resolve().parent
REPO_ROOT = ASSEMBLY_DIR.parents[1]
DEFAULT_RECIPE = ASSEMBLY_DIR / "reviews" / "assembly.yaml"
DEFAULT_SDF = REPO_ROOT / "exports" / "DSG-000095835" / "DSG-000095835.sdf"
TOLERANCE = 1e-8


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def vector(value: Any, label: str) -> np.ndarray:
    result = np.asarray(value, dtype=float)
    require(result.shape == (3,) and np.isfinite(result).all(), f"Invalid {label}: {value}")
    return result


def joint_motion(joint: dict[str, Any], position: float) -> np.ndarray:
    """Closed-form motion about the recipe's world-at-CAD-home axis and pivot."""
    axis = joint["axis"]
    result = np.eye(4)
    if joint["type"] == "prismatic":
        result[:3, 3] = axis * position
    else:
        x, y, z = axis
        cross = np.array([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]])
        rotation = np.eye(3) + np.sin(position) * cross + (1.0 - np.cos(position)) * (cross @ cross)
        result[:3, :3] = rotation
        result[:3, 3] = joint["origin"] - rotation @ joint["origin"]
    return result


def read_recipe(path: Path) -> tuple[list[str], list[dict[str, Any]], str]:
    recipe = yaml.safe_load(path.read_text(encoding="utf-8"))
    require(isinstance(recipe, dict), "Recipe must be a YAML mapping")
    raw_bodies = recipe.get("bodies")
    require(isinstance(raw_bodies, dict) and bool(raw_bodies), "Recipe has no bodies")
    bodies = [_safe_name(str(name)) for name in raw_bodies]
    require(len(bodies) == len(set(bodies)), "Body names collide after SDF normalization")
    raw_joints = recipe.get("joints")
    require(isinstance(raw_joints, list) and bool(raw_joints), "Recipe has no joints")
    joints = []
    for item in raw_joints:
        name = _safe_name(str(item["name"]))
        kind = str(item["type"])
        require(kind in {"prismatic", "revolute"}, f"Unsupported joint type for {name}: {kind}")
        axis = vector(item["axis_xyz"], f"axis for {name}")
        norm = float(np.linalg.norm(axis))
        require(abs(norm - 1.0) <= 1e-5, f"Axis for {name} is not unit length: {norm}")
        origin = vector(item["origin_m"], f"origin for {name}")
        limits = np.asarray(item["limits"], dtype=float)
        require(
            limits.shape == (2,)
            and np.isfinite(limits).all()
            and limits[0] < limits[1]
            and limits[0] <= 0.0 <= limits[1],
            f"Invalid limits or CAD zero outside limits for {name}: {limits}",
        )
        home = float(item.get("home", 0.0))
        require(np.isfinite(home) and abs(home) <= TOLERANCE, f"CAD home is not zero: {name}")
        parent = _safe_name(str(item["parent"]))
        child = _safe_name(str(item["child"]))
        require(parent in bodies and child in bodies, f"Unknown parent/child body for {name}")
        require(parent != child, f"Self-parented joint: {name}")
        joints.append(
            {
                "name": name,
                "type": kind,
                "parent": parent,
                "child": child,
                "axis": axis / norm,
                "origin": origin,
                "limits": limits,
            }
        )
    require(len({joint["name"] for joint in joints}) == len(joints), "Duplicate joint names")
    parents = Counter(joint["child"] for joint in joints)
    require(all(count == 1 for count in parents.values()), "Body has multiple parent joints")
    roots = set(bodies) - set(parents)
    require(len(roots) == 1, f"Expected one anchored root body, got {sorted(roots)}")
    root = roots.pop()
    reached = {root}
    while True:
        extended = reached | {joint["child"] for joint in joints if joint["parent"] in reached}
        if extended == reached:
            break
        reached = extended
    require(reached == set(bodies), "Joint graph is cyclic or disconnected")
    return bodies, joints, root


def resolve_sdf(path: Path) -> Path:
    if path.is_dir():
        candidates = sorted(
            item for item in path.glob("*.sdf") if not item.stem.endswith("_matlab")
        )
        require(len(candidates) == 1, f"Expected one Drake SDF in {path}: {candidates}")
        path = candidates[0]
    require(path.is_file(), f"SDF not found: {path}; run build.py first")
    return path.resolve()


def validate(sdf: Path, recipe_path: Path, *, collision: bool = False) -> None:
    bodies, joints, root = read_recipe(recipe_path)
    scene = load_scene(sdf)
    plant = scene.plant
    context = scene.create_context()
    plant_context = plant.GetMyMutableContextFromRoot(context)
    moving = {
        plant.get_joint(JointIndex(index)).name()
        for index in range(plant.num_joints())
        if plant.get_joint(JointIndex(index)).num_positions()
    }
    require(
        moving == {joint["name"] for joint in joints}, "Compiled joint names differ from recipe"
    )
    require(
        plant.num_positions() == len(joints), "Unexpected floating body or joint position count"
    )
    require(plant.num_bodies() == len(bodies) + 1, "Compiled body count differs from recipe")
    body_objects = {name: plant.GetBodyByName(name) for name in bodies}
    require(
        np.allclose(plant.GetPositions(plant_context), 0.0, atol=TOLERANCE, rtol=0.0),
        "Drake default pose is not the zero CAD home",
    )

    def check_pose(name: str, expected: np.ndarray, label: str) -> float:
        actual = body_objects[name].EvalPoseInWorld(plant_context).GetAsMatrix4()
        error = float(np.max(np.abs(actual - expected)))
        require(
            np.isfinite(actual).all() and error <= TOLERANCE,
            f"{label}: {name} pose error {error:g}",
        )
        return error

    worst_error = max(check_pose(name, np.eye(4), "CAD home") for name in bodies)
    for joint in joints:
        compiled = plant.GetJointByName(joint["name"])
        expected_class = PrismaticJoint if joint["type"] == "prismatic" else RevoluteJoint
        require(isinstance(compiled, expected_class), f"Wrong joint type: {joint['name']}")
        require(
            compiled.parent_body().name() == joint["parent"]
            and compiled.child_body().name() == joint["child"],
            f"Wrong parent/child topology: {joint['name']}",
        )
        actual_limits = [compiled.position_lower_limits()[0], compiled.position_upper_limits()[0]]
        require(
            np.allclose(actual_limits, joint["limits"], atol=TOLERANCE, rtol=0.0),
            f"Wrong joint limits: {joint['name']}",
        )
        frame = compiled.frame_on_parent().CalcPoseInWorld(plant_context)
        axis = (
            compiled.translation_axis()
            if joint["type"] == "prismatic"
            else compiled.revolute_axis()
        )
        require(
            np.allclose(frame.rotation().matrix() @ axis, joint["axis"], atol=TOLERANCE, rtol=0.0),
            f"Wrong world axis: {joint['name']}",
        )
        require(
            np.allclose(frame.translation(), joint["origin"], atol=TOLERANCE, rtol=0.0),
            f"Wrong world pivot/origin: {joint['name']}",
        )
        joint["position_index"] = compiled.position_start()

    def check_configuration(values: dict[str, float], label: str) -> None:
        nonlocal worst_error
        positions = np.zeros(plant.num_positions())
        for joint in joints:
            positions[joint["position_index"]] = values.get(joint["name"], 0.0)
        plant.SetPositions(plant_context, positions)
        expected = {root: np.eye(4)}
        while len(expected) < len(bodies):
            for joint in joints:
                if joint["parent"] in expected and joint["child"] not in expected:
                    expected[joint["child"]] = expected[joint["parent"]] @ joint_motion(
                        joint, values.get(joint["name"], 0.0)
                    )
        worst_error = max(
            worst_error, *(check_pose(name, expected[name], label) for name in bodies)
        )

    for joint in joints:
        for side, position in zip(("lower", "upper"), joint["limits"], strict=True):
            check_configuration({joint["name"]: float(position)}, f"{joint['name']} {side}")
    for index, side in enumerate(("lower", "upper")):
        check_configuration(
            {joint["name"]: float(joint["limits"][index]) for joint in joints}, f"All joints {side}"
        )
    check_configuration({}, "Return to CAD home")
    kinds = Counter(joint["type"] for joint in joints)
    print(f"Validated {len(bodies)} bodies and {len(joints)} joints ({dict(kinds)}).")
    print("CAD home, axes, pivots, limits, descendants, and unaffected branches match the recipe.")
    print(f"Checked {2 * len(joints)} individual endpoints and both combined endpoints.")
    print(f"Maximum pose-matrix error: {worst_error:.3g} (tolerance {TOLERANCE:g}).")

    if collision:
        from collision_view import AssemblyCollisionModel
        from pydrake.geometry import Role

        inspector = scene.scene_graph.model_inspector()
        count = len(inspector.GetAllGeometryIds(Role.kProximity))
        require(count > 0, "--collision requires an SDF built with collision geometry")
        model = AssemblyCollisionModel(scene)
        from twin_lab.collision import part_of

        recipe = yaml.safe_load(recipe_path.read_text())
        cage_refs = set(recipe.get("fixed_subsystems", {}).get("cage", {}).get("parts", []))
        collision_refs = {
            part_of(inspector.GetName(gid)) for gid in inspector.GetAllGeometryIds(Role.kProximity)
        }
        require(cage_refs <= collision_refs, "Some cage members have no collision geometry")
        expected_refs = {
            part if isinstance(part, str) else part["ref"]
            for body in recipe["bodies"].values()
            for part in body["parts"]
        }
        require(expected_refs <= collision_refs, "Some retained parts have no collision geometry")
        # The root joint must check its carriage against the outer cage, even
        # though both sides of that joint are normally filtered by Drake.
        query = scene.scene_graph.get_query_output_port().Eval(
            scene.scene_graph.GetMyContextFromRoot(model.context)
        )
        actual_inspector = query.inspector()
        cages = [
            gid
            for gid in actual_inspector.GetAllGeometryIds(Role.kProximity)
            if part_of(actual_inspector.GetName(gid)) in cage_refs
        ]
        carriage_frame = plant.GetBodyFrameIdOrThrow(plant.GetBodyByName("parker_lift").index())
        carriage_geometry = actual_inspector.GetGeometries(carriage_frame, Role.kProximity)
        require(
            all(
                not actual_inspector.CollisionFiltered(a, b)
                for a in cages
                for b in carriage_geometry
            ),
            "Cage-to-large-slide collision checking is filtered out",
        )
        print(f"All {len(cage_refs)} cage members participate in large-slide collision checking.")
        report = model.report(warn_m=0.001)
        require(
            all(np.isfinite(item.distance_m) for item in report.clearances),
            "Collision query returned a non-finite distance",
        )
        print(
            f"Collision query at CAD home: {count} geometries, {report.status}, "
            f"{len(report.touching_pairs)} touching pairs, "
            f"{len(report.warning_pairs)} pairs within 1 mm."
        )
        print("Contact counts are diagnostic; this check does not certify physical clearance.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "sdf", nargs="?", type=Path, default=DEFAULT_SDF, help="SDF file or package directory"
    )
    parser.add_argument("--recipe", type=Path, default=DEFAULT_RECIPE, help="Assembly recipe YAML")
    parser.add_argument(
        "--collision", action="store_true", help="Also run a CAD-home collision query"
    )
    args = parser.parse_args()
    try:
        validate(resolve_sdf(args.sdf), args.recipe.resolve(), collision=args.collision)
    except (ValueError, KeyError, OSError, RuntimeError) as error:
        parser.exit(1, f"Validation failed: {error}\n")


if __name__ == "__main__":
    main()
