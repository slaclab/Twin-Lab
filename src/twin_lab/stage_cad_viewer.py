"""Responsive viewer for reusable stage CAD occurrences."""

from __future__ import annotations

import json
import math
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from OCP.Bnd import Bnd_Box
from OCP.BRep import BRep_Tool
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS

from .cad_geometry import leaf_occurrences, placed_shape, write_group_obj
from .constraints_wizard import _occurrence_shape_by_ref, _read_step_document
from .epics_playback import PlaybackSource
from .paths import CACHE_ROOT, resolve_repo_path, review_artifact_stem

AUTO_MOTION_LABEL = "Animation"
AUTO_RANGE_LABEL = "Auto motion range (% of travel)"
AUTO_PERIOD_LABEL = "Auto motion period (s)"
PLAYBACK_SPEED_LABEL = "Playback speed (x)"
PLAYBACK_PAUSED_LABEL = "Playback: paused"
TRAVEL_SPEED_LABEL = "Travel speed (% of max)"
SCRUB_LABEL = "Playback position (% of completion)"
CONTINUOUS_STOP_LABEL = "Stop continuous playback"
CONTINUOUS_RESUME_LABEL = "Resume continuous playback"
ONGOING_PLAYBACK_ENDS = {"ongoing", "continuous"}
ONGOING_PLAYBACK_RESUME_STARTS = {"resume", "previous", "last"}
DEFAULT_ONGOING_RESUME_PATH = Path("recordings/ongoing-playback-resume.json")
# While animating, the sliders report the pose rather than drive it, so they only have to
# keep up with the eye. Pushing all of them every frame costs a dat.GUI redraw each, which
# is far more work than the browser can absorb at the frame rate.
SLIDER_PUSH_HZ = 5.0
# A joint holding between commands publishes nothing, so motion is reported for this long
# after the last change to keep the readout from flickering during slow moves.
MOTION_HOLD_S = 0.5
# The browser readout only repaints twice a second, so pushing the clock faster than that
# would just queue updates the viewer never shows.
TIME_PUSH_S = 0.5


def prepare_stage_cad(
    inventory_path: str | Path,
    *,
    rebuild: bool = False,
    linear_deflection_mm: float = 2.0,
) -> Path:
    """Cache one real CAD mesh per reusable model plus occurrence transforms."""

    inventory_file = resolve_repo_path(inventory_path).resolve()
    inventory = yaml.safe_load(inventory_file.read_text(encoding="utf-8"))
    step_path = resolve_repo_path(inventory["source_step"], relative_to=inventory_file.parent)
    catalog_path = resolve_repo_path(inventory["stage_catalog"], relative_to=inventory_file.parent)
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))["stages"]
    visual_styles = inventory.get("visual_styles", {})
    stage_colors = visual_styles.get("stage_models", {})
    manifest_path = resolve_repo_path(inventory["cad_manifest"], relative_to=inventory_file.parent)
    output_dir = CACHE_ROOT / "stage-cad" / review_artifact_stem(inventory_file)
    scene_path = output_dir / "scene.yaml"
    sources = [inventory_file, step_path, catalog_path, manifest_path]
    if not rebuild and scene_path.exists():
        cached_scene = yaml.safe_load(scene_path.read_text(encoding="utf-8"))
        cached_meshes = {Path(item["mesh"]) for item in cached_scene.get("instances", [])}
        if cached_scene.get("schema") == "slac-stage-cad-scene/v8" and cached_scene.get(
            "attachments"
        ):
            cached_meshes.update(Path(item["mesh"]) for item in cached_scene["attachments"])
            cached_meshes.update(
                Path(item["mesh"]) for item in cached_scene.get("static_geometry", [])
            )
            for stage_meshes in cached_scene.get("motion_stage_meshes", {}).values():
                cached_meshes.update(Path(path) for path in stage_meshes.values())
            if cached_meshes and _is_current([scene_path, *cached_meshes], sources):
                return scene_path

    output_dir.mkdir(parents=True, exist_ok=True)
    document, _, roots = _read_step_document(step_path)
    assert document is not None
    geometries: dict[str, list[tuple[str, Any, Path]]] = {}
    instances = []
    for instance in inventory["stage_instances"]:
        model_id = str(instance["catalog"])
        shape, location = _occurrence_shape_by_ref(roots, str(instance["ref"]))
        model_geometries = geometries.setdefault(model_id, [])
        matched = next((item for item in model_geometries if shape.IsSame(item[1])), None)
        if matched is None:
            number = len(model_geometries) + 1
            geometry_id = model_id if number == 1 else f"{model_id}__definition_{number}"
            mesh_path = output_dir / f"{geometry_id}.obj"
            matched = (geometry_id, shape, mesh_path)
            model_geometries.append(matched)
        geometry_id, _, mesh_path = matched
        instances.append(
            {
                "ref": str(instance["ref"]),
                "library_id": str(instance["library_id"]),
                "catalog": model_id,
                "geometry_id": geometry_id,
                "model": str(catalog[model_id]["model"]),
                "joint_type": str(catalog[model_id]["joint_type"]),
                "rgba": [
                    float(value) for value in stage_colors.get(model_id, [0.6, 0.6, 0.6, 1.0])
                ],
                "mesh": mesh_path.as_posix(),
                **_transform_data(location.Transformation()),
            }
        )

    for model_geometries in geometries.values():
        for _, shape, mesh_path in model_geometries:
            _write_shape_obj(shape, mesh_path, linear_deflection_mm)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_items = manifest["occurrences"]
    by_ref = {item["ref"]: item for item in manifest_items}
    root_id = by_ref[inventory["subassembly"]["ref"]]["id"]
    stage_ids = [by_ref[str(item["ref"])]["id"] for item in inventory["stage_instances"]]
    hidden_refs = {str(ref) for ref in inventory.get("hidden_occurrences", [])}
    overrides = inventory.get("attachment_overrides", {})
    forced_fixed = {str(ref) for ref in overrides.get("fixed", [])}
    forced_parent = {
        str(ref): str(parent_ref)
        for parent_ref, references in overrides.get("moving", {}).items()
        for ref in references
    }
    # A reviewed attachment may name a part outside the focused subassembly, because a
    # stack elsewhere in the STEP can still carry payload that has to move with it.
    reviewed_refs = forced_fixed | set(forced_parent)
    attached_refs = [
        item["ref"]
        for item in manifest_items
        if not item["is_assembly"]
        and (item["id"].startswith(f"{root_id}/") or item["ref"] in reviewed_refs)
        and not any(item["id"].startswith(f"{stage_id}/") for stage_id in stage_ids)
        and not _is_fastener_name(str(item["name"]))
        and item["ref"] not in hidden_refs
    ]
    leaves = leaf_occurrences(roots)

    static_geometry = []
    used_static_refs: set[str] = set()
    for spec in inventory.get("static_geometry", []):
        source_ref = str(spec["ref"])
        source = by_ref[source_ref]
        source_id = str(source["id"])
        references = [
            str(item["ref"])
            for item in manifest_items
            if not item["is_assembly"]
            and (item["id"] == source_id or item["id"].startswith(f"{source_id}/"))
            and not _is_fastener_name(str(item["name"]))
            and item["ref"] not in hidden_refs
        ]
        duplicate_refs = used_static_refs.intersection(references)
        if duplicate_refs:
            raise ValueError(
                f"Static geometry {source_ref} overlaps another selected group: "
                f"{sorted(duplicate_refs)}"
            )
        if not references:
            raise ValueError(f"Static geometry {source_ref} contains no non-fastener parts")
        used_static_refs.update(references)
        mesh_path = output_dir / f"static_{source_ref}.obj"
        write_group_obj(
            [leaves[ref] for ref in references],
            mesh_path,
            linear_deflection_mm=linear_deflection_mm,
        )
        static_geometry.append(
            {
                "source_ref": source_ref,
                "name": str(spec["name"]),
                "cad_id": str(spec.get("cad_id", source["name"])),
                "mesh": mesh_path.as_posix(),
                "part_count": len(references),
                "rgba": [float(value) for value in spec.get("rgba", [0.48, 0.52, 0.58, 1.0])],
            }
        )

    instance_by_ref = {item["ref"]: item for item in instances}
    motion_stage_meshes: dict[str, dict[str, str]] = {}
    motion_stage_roles: dict[str, set[str]] = {}
    for references in inventory.get("motion_chains", {}).values():
        for ref in references:
            motion_stage_roles.setdefault(str(ref), set()).update(("fixed", "moving"))
    for specs in inventory.get("compound_motion_chains", {}).values():
        for spec in specs:
            roles = motion_stage_roles.setdefault(str(spec["stage_ref"]), set())
            if spec.get("fixed_role"):
                roles.add(str(spec["fixed_role"]))
            roles.add(str(spec["moving_role"]))
    for stage_ref, requested_roles in motion_stage_roles.items():
        stage_item = instance_by_ref[stage_ref]
        roles = catalog[stage_item["catalog"]]["component_roles"]
        children = [item for item in manifest_items if item["parent_id"] == by_ref[stage_ref]["id"]]
        role_meshes = {}
        for role in sorted(requested_roles):
            references = [children[index - 1]["ref"] for index in roles[role]]
            mesh_path = output_dir / f"{stage_ref}_{role}.obj"
            write_group_obj(
                [leaves[ref] for ref in references],
                mesh_path,
                linear_deflection_mm=linear_deflection_mm,
            )
            role_meshes[role] = mesh_path.as_posix()
        motion_stage_meshes[stage_ref] = role_meshes

    attachment_styles = visual_styles.get("attachment_groups", {})
    attachment_style_by_ref: dict[str, str] = {}
    attachment_rgba_by_style: dict[str, list[float]] = {}
    for style, spec in attachment_styles.items():
        attachment_rgba_by_style[str(style)] = [float(value) for value in spec["rgba"]]
        for ref in spec["refs"]:
            reference = str(ref)
            if reference in attachment_style_by_ref:
                raise ValueError(f"Attachment {reference} has more than one visual style")
            attachment_style_by_ref[reference] = str(style)

    attachment_groups: dict[tuple[str | None, str], list[str]] = {}
    chain_root_by_id = {
        os.path.commonpath([by_ref[str(ref)]["id"] for ref in refs]): refs
        for refs in inventory.get("motion_chains", {}).values()
    }
    for reference in attached_refs:
        if reference in forced_fixed:
            style = attachment_style_by_ref.get(reference, "default")
            attachment_groups.setdefault((None, style), []).append(reference)
            continue
        if reference in forced_parent:
            style = attachment_style_by_ref.get(reference, "default")
            attachment_groups.setdefault((forced_parent[reference], style), []).append(reference)
            continue
        occurrence_id = by_ref[reference]["id"]
        chain_refs = next(
            (
                refs
                for branch_id, refs in chain_root_by_id.items()
                if occurrence_id.startswith(f"{branch_id}/")
            ),
            None,
        )
        if chain_refs is None:
            style = attachment_style_by_ref.get(reference, "default")
            attachment_groups.setdefault((None, style), []).append(reference)
            continue
        center_m = _shape_center_m(placed_shape(leaves[reference]))
        parent_ref = min(
            chain_refs,
            key=lambda ref: math.dist(center_m, instance_by_ref[ref]["translation_m"]),
        )
        style = attachment_style_by_ref.get(reference, "default")
        attachment_groups.setdefault((parent_ref, style), []).append(reference)

    attachments = []
    for (parent_ref, style), references in attachment_groups.items():
        if not references:
            continue
        name = "fixed" if parent_ref is None else parent_ref
        mesh_path = output_dir / f"attached_{name}_{style}.obj"
        write_group_obj(
            [leaves[ref] for ref in references],
            mesh_path,
            linear_deflection_mm=linear_deflection_mm,
        )
        attachments.append(
            {
                "parent_stage_ref": parent_ref,
                "mesh": mesh_path.as_posix(),
                "part_count": len(references),
                "style": style,
                "rgba": attachment_rgba_by_style.get(
                    style,
                    [0.45, 0.68, 0.78, 1.0] if parent_ref is not None else [0.68, 0.68, 0.70, 1.0],
                ),
            }
        )

    motion_chains = []
    for chain_name, references in inventory.get("motion_chains", {}).items():
        joints = []
        for reference in references:
            item = instance_by_ref[str(reference)]
            stage = catalog[item["catalog"]]
            axis_local = stage.get("axis_local")
            if axis_local is None or not isinstance(stage.get("limits"), list):
                continue
            axis_world = _rotate_vector(item["rotation"], axis_local)
            joints.append(
                {
                    "key": item["ref"],
                    "ref": item["ref"],
                    "stack": str(chain_name),
                    "name": "motion",
                    "model": item["model"],
                    "joint_type": item["joint_type"],
                    "fixed_role": "fixed",
                    "moving_role": "moving",
                    "axis_world": axis_world,
                    "origin_m": _joint_origin_m(item, stage),
                    "limits": _reviewed_limits(
                        inventory, item["ref"], item["ref"], stage["limits"]
                    ),
                    "home": _reviewed_home(inventory, item["ref"], item["ref"]),
                    "cad_position": _reviewed_cad_position(inventory, item["ref"], item["ref"]),
                }
            )
        motion_chains.append({"name": str(chain_name), "joints": joints})

    for chain_name, specs in inventory.get("compound_motion_chains", {}).items():
        joints = []
        for spec in specs:
            item = instance_by_ref[str(spec["stage_ref"])]
            key = str(spec["key"])
            joints.append(
                {
                    "key": key,
                    "ref": item["ref"],
                    "stack": str(chain_name),
                    "name": str(spec["name"]),
                    "model": item["model"],
                    "joint_type": "prismatic",
                    "fixed_role": spec.get("fixed_role"),
                    "moving_role": str(spec["moving_role"]),
                    "axis_world": _rotate_vector(item["rotation"], spec["axis_local"]),
                    "origin_m": item["translation_m"],
                    "limits": _reviewed_limits(inventory, key, item["ref"], spec["limits"]),
                    "home": _reviewed_home(inventory, key, item["ref"]),
                    "cad_position": float(spec.get("cad_position", 0.0)),
                }
            )
        motion_chains.append({"name": str(chain_name), "joints": joints})

    scene = {
        "schema": "slac-stage-cad-scene/v8",
        "source_inventory": inventory_file.as_posix(),
        "linear_deflection_mm": linear_deflection_mm,
        "instances": instances,
        "static_geometry": static_geometry,
        "attached_part_count": len(attached_refs),
        "attachments": attachments,
        "motion_stage_meshes": motion_stage_meshes,
        "motion_chains": motion_chains,
    }
    scene_path.write_text(yaml.safe_dump(scene, sort_keys=False), encoding="utf-8")
    return scene_path


def view_stage_cad(
    scene_path: str | Path,
    *,
    fps: float = 30.0,
    playback: PlaybackSource | None = None,
    joint_labels: dict[str, str] | None = None,
    port: int | None = None,
    open_browser: bool = True,
) -> None:
    """Show reusable real-CAD meshes with one transform per occurrence.

    `joint_labels` (joint key -> display label) is only used in the playback
    terminal readout, e.g. to show EPICS PV names instead of joint refs.

    If `playback` is given, every joint it has a track for is driven from the
    recorded session instead of its slider/animation value each frame; other
    joints keep the existing manual/auto-motion behavior.
    """

    from pydrake.geometry import Mesh, Meshcat, Rgba
    from pydrake.math import RigidTransform, RotationMatrix

    from .meshcat_ui import (
        MODE_CONTINUOUS_PLAYBACK,
        MODE_ARCHIVE,
        MODE_LIVE,
        MODE_NONE,
        STATUS_COMPLETE,
        STATUS_NONE,
        STATUS_STANDBY,
        announce_viewer,
        patch_meshcat_page,
        print_view_help,
        set_motors_moving,
        set_playback_time,
        set_viewer_mode,
        set_viewer_status,
        should_open_browser,
        viewer_params,
    )

    scene = yaml.safe_load(Path(scene_path).read_text(encoding="utf-8"))
    instances = scene["instances"]
    # Nothing here publishes a realtime rate, so the stats plot only ever covers the view.
    patch_meshcat_page()
    try:
        meshcat = Meshcat(viewer_params(port=port))
    except RuntimeError:
        # Another viewer already holds the fixed port; taking any free one beats refusing
        # to start, but say so, because the URL to refresh is now a different one.
        print(f"Port {port} is already in use, so this viewer took another one.")
        meshcat = Meshcat(viewer_params())
    # Streaming this much CAD takes a while, so the readout says so before it starts.
    set_viewer_status(meshcat, STATUS_STANDBY)
    role_paths: dict[tuple[str, str], str] = {}
    joint_paths: dict[str, str] = {}
    last_joint_path_by_stage: dict[str, str] = {}
    for chain in scene.get("motion_chains", []):
        parent_path = f"/chains/{chain['name']}"
        for joint in chain["joints"]:
            reference = joint["ref"]
            fixed_role = joint.get("fixed_role")
            if fixed_role:
                role_paths[(reference, fixed_role)] = (
                    f"{parent_path}/{reference} {fixed_role} geometry"
                )
            joint_path = f"{parent_path}/{joint['key']} motion"
            joint_paths[joint["key"]] = joint_path
            last_joint_path_by_stage[reference] = joint_path
            role_paths[(reference, joint["moving_role"])] = (
                f"{joint_path}/{reference} {joint['moving_role']} geometry"
            )
            parent_path = joint_path
    for item in instances:
        if item["ref"] in scene["motion_stage_meshes"]:
            meshes = scene["motion_stage_meshes"][item["ref"]]
            for role, mesh_path in meshes.items():
                meshcat.SetObject(
                    role_paths[(item["ref"], role)],
                    Mesh(Path(mesh_path), 1.0),
                    Rgba(*item["rgba"]),
                )
            continue
        path = f"/stages/{item['ref']} {item['model']}"
        meshcat.SetObject(
            path,
            Mesh(Path(item["mesh"]), 1.0),
            Rgba(*item["rgba"]),
        )
        meshcat.SetTransform(
            path,
            RigidTransform(RotationMatrix(item["rotation"]), item["translation_m"]),
        )

    for attachment in scene["attachments"]:
        parent_ref = attachment["parent_stage_ref"]
        style = attachment.get("style", "default")
        if parent_ref in last_joint_path_by_stage:
            path = f"{last_joint_path_by_stage[parent_ref]}/{style} geometry"
        elif parent_ref is not None:
            path = f"/pending motion/{parent_ref}/{style} geometry"
        else:
            path = f"/attached geometry/fixed/{style}"
        meshcat.SetObject(
            path,
            Mesh(Path(attachment["mesh"]), 1.0),
            Rgba(*attachment["rgba"]),
        )

    for item in scene.get("static_geometry", []):
        path = f"/environment/{item['source_ref']} {item['name']}"
        rgba = item.get("rgba", [0.48, 0.52, 0.58, 1.0])
        meshcat.SetObject(
            path,
            Mesh(Path(item["mesh"]), 1.0),
            Rgba(*rgba),
        )

    joints = [joint for chain in scene.get("motion_chains", []) for joint in chain["joints"]]
    playback_keys = {joint["key"] for joint in joints if playback and joint["key"] in playback.joint_names}
    # Playback/live modes are view-only: the recording (or the real hardware) is the only
    # thing allowed to move a joint, so the manual sliders and cyclic-animation controls
    # that would otherwise fight it are left off entirely.
    has_playback_controls = playback is not None and hasattr(playback, "set_speed")
    has_travel_control = playback is not None and hasattr(playback, "set_travel_fraction")
    has_ongoing_controls = playback is not None and hasattr(playback, "stop_feed")
    if playback is None:
        for joint in joints:
            scale, unit = _slider_scale(joint)
            meshcat.AddSlider(
                _slider_label(joint, unit),
                joint["limits"][0] * scale,
                joint["limits"][1] * scale,
                0.1,
                joint["home"] * scale,
            )
        # Drake can publish a slider but not a checkbox, so this steps 0 to 1 and
        # meshcat_ui.TOGGLE_JS swaps a real checkbox into its row.
        meshcat.AddSlider(AUTO_MOTION_LABEL, 0.0, 1.0, 1.0, 0.0)
        meshcat.AddSlider(AUTO_RANGE_LABEL, 0.0, 100.0, 1.0, 25.0)
        meshcat.AddSlider(AUTO_PERIOD_LABEL, 2.0, 60.0, 0.5, 12.0)
    if has_playback_controls:
        meshcat.AddSlider(PLAYBACK_SPEED_LABEL, 0.1, 8.0, 0.05, playback.speed)
        meshcat.AddSlider(PLAYBACK_PAUSED_LABEL, 0.0, 1.0, 1.0, 1.0 if playback.is_paused else 0.0)
        meshcat.AddButton("Restart playback")
    if has_travel_control:
        meshcat.AddSlider(TRAVEL_SPEED_LABEL, 0.0, 100.0, 1.0, playback.travel_fraction * 100.0)
    if has_ongoing_controls:
        meshcat.AddButton(CONTINUOUS_STOP_LABEL)
        meshcat.AddButton(CONTINUOUS_RESUME_LABEL)
    can_scrub = playback is not None and getattr(playback, "record_end", None) is not None
    if can_scrub:
        meshcat.AddSlider(SCRUB_LABEL, 0.0, 100.0, 0.1, 0.0)

    center = [
        sum(item["translation_m"][axis] for item in instances) / len(instances) for axis in range(3)
    ]
    eye = [center[0] + 0.8, center[1] + 0.8, center[2] + 0.8]
    # pydrake's stub gives SetCameraPose a malformed Eigen shape; lists convert at runtime.
    meshcat.SetCameraPose(eye, center)  # pyright: ignore[reportArgumentType]
    if playback is None:
        meshcat.AddButton("Reset to home")
    stop_label = "Stop live feed" if playback is not None and not (has_playback_controls or has_ongoing_controls) else "Stop viewer"
    meshcat.AddButton(stop_label, "Escape")
    announce_viewer("Reusable stage CAD", meshcat, open_browser=should_open_browser(open_browser))
    print(
        f"Showing {len(instances)} real stages and {scene['attached_part_count']} attached "
        "non-fastener parts."
    )
    if playback is None:
        print(f"Motion sliders: {len(joints)}")
        print("Tick 'Animation' to start and stop cyclic motion.")
    elif playback_keys:
        label = "Continuous playback" if has_ongoing_controls else "Live EPICS feed" if not has_playback_controls else "Playback"
        if getattr(playback, "has_commands", True):
            if has_ongoing_controls:
                print(
                    f"{label}: replaying archived EPICS commands for {len(playback_keys)} "
                    "joint(s) at 1x. Use the Meshcat stop/resume buttons to control the feed."
                )
            else:
                print(
                    f"{label}: recreating recorded EPICS commands for {len(playback_keys)} joint(s). "
                    "This is view-only - use the Meshcat panel controls to pause/speed/restart it."
                )
        else:
            print(
                f"{label}: no commands in this window, so nothing will move. Showing the "
                "assembly at its reviewed home - check the time window if that's unexpected."
            )
    print_view_help()
    print("Press Escape in Meshcat or Ctrl-C here to stop.")
    frame_period = 1.0 / max(fps, 1.0)
    slider_period = 1.0 / SLIDER_PUSH_HZ
    reset_clicks = 0
    restart_clicks = 0
    continuous_stop_clicks = 0
    continuous_resume_clicks = 0
    phase = 0.0
    previous_tick = time.monotonic()
    last_slider_push = 0.0
    was_automatic = False
    scales = [_slider_scale(joint)[0] for joint in joints]
    labels = [_slider_label(joint, _slider_scale(joint)[1]) for joint in joints]
    homes = [joint["home"] * scale for joint, scale in zip(joints, scales, strict=True)]
    values = list(homes)
    published: list[float | None] = [None] * len(joints)
    last_speed_value = playback.speed if has_playback_controls else None
    last_paused_value = playback.is_paused if has_playback_controls else None
    last_travel_value = playback.travel_fraction * 100.0 if has_travel_control else None
    last_readout = 0.0
    last_motion_tick = float("-inf")
    reported_moving: bool | None = None
    last_time_push = 0.0
    last_scrub_value = 0.0
    reported_status = STATUS_STANDBY
    set_motors_moving(meshcat, False)
    set_viewer_status(meshcat, STATUS_NONE)
    if playback is None:
        set_viewer_mode(meshcat, MODE_NONE)
    elif getattr(playback, "is_ongoing_playback", False):
        set_viewer_mode(meshcat, MODE_CONTINUOUS_PLAYBACK)
    else:
        set_viewer_mode(meshcat, MODE_ARCHIVE if has_playback_controls else MODE_LIVE)
    while meshcat.GetButtonClicks(stop_label) == 0:
        tick = time.monotonic()
        elapsed = tick - previous_tick
        previous_tick = tick
        if playback is not None:
            if has_travel_control:
                travel_value = meshcat.GetSliderValue(TRAVEL_SPEED_LABEL)
                if travel_value != last_travel_value:
                    playback.set_travel_fraction(travel_value / 100.0)
                    last_travel_value = travel_value
            if has_playback_controls:
                speed_value = meshcat.GetSliderValue(PLAYBACK_SPEED_LABEL)
                if speed_value != last_speed_value:
                    playback.set_speed(max(speed_value, 0.05))
                    last_speed_value = speed_value
                paused_value = meshcat.GetSliderValue(PLAYBACK_PAUSED_LABEL) >= 0.5
                if paused_value != last_paused_value:
                    (playback.pause if paused_value else playback.resume)()
                    last_paused_value = paused_value
                new_restart_clicks = meshcat.GetButtonClicks("Restart playback")
                if new_restart_clicks != restart_clicks:
                    restart_clicks = new_restart_clicks
                    playback.restart()
            if has_ongoing_controls:
                new_stop_clicks = meshcat.GetButtonClicks(CONTINUOUS_STOP_LABEL)
                if new_stop_clicks != continuous_stop_clicks:
                    continuous_stop_clicks = new_stop_clicks
                    playback.stop_feed(tick)
                new_resume_clicks = meshcat.GetButtonClicks(CONTINUOUS_RESUME_LABEL)
                if new_resume_clicks != continuous_resume_clicks:
                    continuous_resume_clicks = new_resume_clicks
                    playback.resume_feed(tick)
            if can_scrub:
                scrub_value = meshcat.GetSliderValue(SCRUB_LABEL)
                # Only a viewer-side move counts as a seek; the loop writes this slider
                # back every frame to track progress, which must not seek onto itself.
                if abs(scrub_value - last_scrub_value) > 1e-9:
                    playback.seek_fraction(scrub_value / 100.0)
                    last_scrub_value = scrub_value
            positions = playback.positions()
            moment = playback.current_moment()
            if tick - last_time_push >= TIME_PUSH_S:
                last_time_push = tick
                set_playback_time(meshcat, moment.timestamp())
                if can_scrub:
                    progress = playback.progress_fraction() * 100.0
                    last_scrub_value = round(progress, 1)
                    meshcat.SetSliderValue(SCRUB_LABEL, last_scrub_value)
                status = (
                    STATUS_COMPLETE
                    if getattr(playback, "is_complete", None) and playback.is_complete()
                    else STATUS_NONE
                )
                if status != reported_status:
                    reported_status = status
                    set_viewer_status(meshcat, status)
            for index, joint in enumerate(joints):
                if joint["key"] in playback_keys:
                    values[index] = positions[joint["key"]] * scales[index]
            # With no manual sliders in this mode, this is the only numeric feedback that
            # values are actually changing (vs. just holding steady between commands).
            if playback_keys and tick - last_readout >= 1.0:
                last_readout = tick
                sample = ", ".join(
                    f"{(joint_labels or {}).get(joint['key'], joint['key'])}="
                    f"{values[index]:+.3f}{_slider_scale(joint)[1]}"
                    for index, joint in enumerate(joints)
                    if joint["key"] in playback_keys
                )
                stamp = moment.astimezone().strftime("%Y-%m-%d %H:%M:%S")
                print(f"[playback {stamp}] {sample}")
        else:
            automatic = meshcat.GetSliderValue(AUTO_MOTION_LABEL) >= 0.5
            new_reset_clicks = meshcat.GetButtonClicks("Reset to home")
            if new_reset_clicks != reset_clicks:
                reset_clicks = new_reset_clicks
                phase = 0.0
                automatic = False
                meshcat.SetSliderValue(AUTO_MOTION_LABEL, 0.0)
                values = list(homes)
                _push_sliders(meshcat, labels, values)
            if automatic:
                period = max(meshcat.GetSliderValue(AUTO_PERIOD_LABEL), 0.1)
                span_fraction = meshcat.GetSliderValue(AUTO_RANGE_LABEL) / 100.0
                phase = math.fmod(phase + 2.0 * math.pi * elapsed / period, 2.0 * math.pi)
                values = []
                for index, joint in enumerate(joints):
                    offset = 2.0 * math.pi * index / max(len(joints), 1)
                    target = joint["home"] + _auto_amplitude(joint, span_fraction) * math.sin(
                        phase + offset
                    )
                    values.append(target * scales[index])
                if tick - last_slider_push >= slider_period:
                    last_slider_push = tick
                    _push_sliders(meshcat, labels, values)
            else:
                if was_automatic:
                    # The sliders only catch up a few times a second while animating, so hand
                    # them the pose that is actually on screen before they become the input.
                    _push_sliders(meshcat, labels, values)
                values = [meshcat.GetSliderValue(label) for label in labels]
            was_automatic = automatic
        for index, joint in enumerate(joints):
            if published[index] == values[index]:
                continue
            published[index] = values[index]
            last_motion_tick = tick
            value = _joint_displacement(joint, values[index] / scales[index])
            if joint["joint_type"] == "prismatic":
                offset = [component * value for component in joint["axis_world"]]
                # pydrake's Eigen stub is malformed; the list converts at runtime.
                transform = RigidTransform(offset)  # pyright: ignore
            else:
                transform = _rotation_about_axis(
                    joint["axis_world"], joint["origin_m"], value, RigidTransform, RotationMatrix
                )
            meshcat.SetTransform(joint_paths[joint["key"]], transform)
        # Held between commands a joint publishes nothing, so a short tail keeps the
        # readout from flickering to "no motors moving" during slow continuous motion.
        moving = (tick - last_motion_tick) < MOTION_HOLD_S
        if moving != reported_moving:
            reported_moving = moving
            set_motors_moving(meshcat, moving)
        # Backpressure. Meshcat buffers without limit, so a loop that publishes faster than
        # the browser can draw builds a queue that never drains, and a stop request cannot
        # be seen until the browser has chewed through it.
        meshcat.Flush()
        frame_cost = time.monotonic() - tick
        time.sleep(max(0.0, frame_period - frame_cost))


def _push_sliders(meshcat, labels: list[str], values: list[float]) -> None:
    for label, value in zip(labels, values, strict=True):
        meshcat.SetSliderValue(label, value)


def _write_shape_obj(shape: Any, output: Path, linear_deflection_mm: float) -> None:
    vertices: list[tuple[float, float, float]] = []
    triangles: list[tuple[int, int, int]] = []
    BRepMesh_IncrementalMesh(shape, linear_deflection_mm, False, 0.5, True).Perform()
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        # OCP's stub omits the bare TopoDS class; Face_s exists at runtime.
        face = TopoDS.Face_s(explorer.Current())  # pyright: ignore[reportAttributeAccessIssue]
        face_location = TopLoc_Location()
        triangulation = BRep_Tool.Triangulation_s(face, face_location)
        if triangulation is not None:
            offset = len(vertices)
            transform = face_location.Transformation()
            for index in range(1, triangulation.NbNodes() + 1):
                point = triangulation.Node(index).Transformed(transform)
                vertices.append((point.X() * 0.001, point.Y() * 0.001, point.Z() * 0.001))
            for index in range(1, triangulation.NbTriangles() + 1):
                triangle = triangulation.Triangle(index)
                n1, n2, n3 = (triangle.Value(i) for i in (1, 2, 3))
                if face.Orientation() == TopAbs_REVERSED:
                    n1, n2, n3 = n3, n2, n1
                triangles.append((offset + n1, offset + n2, offset + n3))
        explorer.Next()

    if not vertices or not triangles:
        raise ValueError(f"Stage produced no mesh triangles: {output.stem}")
    lines = [f"v {x:.9g} {y:.9g} {z:.9g}" for x, y, z in vertices]
    lines.extend(f"f {a} {b} {c}" for a, b, c in triangles)
    output.write_text("\n".join(lines) + "\n", encoding="ascii")


def _transform_data(transform: Any) -> dict[str, list[Any]]:
    rotation = [
        [float(transform.Value(row, column)) for column in range(1, 4)] for row in range(1, 4)
    ]
    for row in rotation:
        for index, value in enumerate(row):
            if math.isclose(value, 0.0, abs_tol=1e-14):
                row[index] = 0.0
    return {
        "rotation": rotation,
        "translation_m": [float(transform.Value(row, 4)) * 0.001 for row in range(1, 4)],
    }


def _is_fastener_name(name: str) -> bool:
    return re.search(r"screw|shcs|fhcs|setscr|heat-set insert", name, re.IGNORECASE) is not None


def _rotate_vector(rotation: list[list[float]], vector: list[float]) -> list[float]:
    result = [
        sum(rotation[row][column] * vector[column] for column in range(3)) for row in range(3)
    ]
    norm = math.sqrt(sum(value * value for value in result))
    return [value / norm for value in result]


def _joint_origin_m(instance: dict[str, Any], stage: dict[str, Any]) -> list[float]:
    offset = [float(value) for value in stage.get("pivot_offset_local", [0.0, 0.0, 0.0])]
    return [
        float(instance["translation_m"][row])
        + sum(float(instance["rotation"][row][column]) * offset[column] for column in range(3))
        for row in range(3)
    ]


def _reviewed_limits(
    inventory: dict[str, Any], key: str, stage_ref: str, default: list[float]
) -> list[float]:
    overrides = inventory.get("joint_limit_overrides", {})
    override = overrides.get(key, overrides.get(stage_ref))
    if override is None:
        return [float(default[0]), float(default[1])]
    limits = [float(value) for value in override["limits"]]
    if override.get("unit") == "degree":
        return [math.radians(value) for value in limits]
    return limits


def _reviewed_home(inventory: dict[str, Any], key: str, stage_ref: str) -> float:
    overrides = inventory.get("joint_limit_overrides", {})
    override = overrides.get(key, overrides.get(stage_ref, {}))
    home = float(override.get("home", 0.0))
    return math.radians(home) if override.get("unit") == "degree" else home


def _reviewed_cad_position(inventory: dict[str, Any], key: str, stage_ref: str) -> float:
    """Where the CAD pose sits on the joint, which is the home unless a review says otherwise.

    A stage assembled at one end of its stroke has a home the CAD pose cannot supply, and the
    meshes are baked at the CAD pose, so the two have to be stated separately.
    """

    overrides = inventory.get("joint_limit_overrides", {})
    override = overrides.get(key, overrides.get(stage_ref, {}))
    if "cad_position" not in override:
        return _reviewed_home(inventory, key, stage_ref)
    position = float(override["cad_position"])
    return math.radians(position) if override.get("unit") == "degree" else position


def _slider_label(joint: dict[str, Any], unit: str) -> str:
    axis_name = "" if joint["name"] == "motion" else f" {joint['name']}"
    return f"{joint['stack']} / {joint['ref']}{axis_name} {joint['model']} ({unit})"


def _slider_scale(joint: dict[str, Any]) -> tuple[float, str]:
    if joint["joint_type"] == "prismatic":
        return 1000.0, "mm"
    return 180.0 / math.pi, "deg"


def _auto_amplitude(joint: dict[str, Any], span_fraction: float) -> float:
    """Largest symmetric excursion about home that stays inside the reviewed limits."""

    home = float(joint["home"])
    reach = min(home - float(joint["limits"][0]), float(joint["limits"][1]) - home)
    return max(reach, 0.0) * span_fraction


def _joint_displacement(joint: dict[str, Any], slider_value: float) -> float:
    return slider_value - float(joint.get("cad_position", joint["home"]))


def _shape_center_m(shape: Any) -> list[float]:
    bounds = Bnd_Box()
    BRepBndLib.Add_s(shape, bounds, False)
    x_min, y_min, z_min, x_max, y_max, z_max = bounds.Get()
    return [(x_min + x_max) * 0.0005, (y_min + y_max) * 0.0005, (z_min + z_max) * 0.0005]


def _rotation_about_axis(axis, origin, angle, rigid_transform_type, rotation_matrix_type):
    x, y, z = axis
    c = math.cos(angle)
    s = math.sin(angle)
    t = 1.0 - c
    matrix = [
        [t * x * x + c, t * x * y - s * z, t * x * z + s * y],
        [t * x * y + s * z, t * y * y + c, t * y * z - s * x],
        [t * x * z - s * y, t * y * z + s * x, t * z * z + c],
    ]
    translation = [
        origin[row] - sum(matrix[row][column] * origin[column] for column in range(3))
        for row in range(3)
    ]
    return rigid_transform_type(rotation_matrix_type(matrix), translation)


def _is_current(outputs: list[Path], sources: list[Path]) -> bool:
    if not all(output.exists() for output in outputs):
        return False
    oldest_output = min(output.stat().st_mtime_ns for output in outputs)
    return all(source.exists() and source.stat().st_mtime_ns <= oldest_output for source in sources)


def _pv_name_labels(command_map_path: str | Path) -> dict[str, str]:
    """joint key -> EPICS PV name, for the playback readout's `--pv-names` toggle."""

    from .epics_playback import load_command_map

    mappings, _ = load_command_map(command_map_path)
    return {key: mapping.command_pv for key, mapping in mappings.items()}


def _is_ongoing_playback_end(value: str) -> bool:
    return value.casefold() in ONGOING_PLAYBACK_ENDS


def _is_ongoing_playback_resume_start(value: str) -> bool:
    return value.casefold() in ONGOING_PLAYBACK_RESUME_STARTS


def _load_ongoing_resume_start(path: str | Path) -> datetime:
    resume_path = resolve_repo_path(path)
    if not resume_path.exists():
        raise SystemExit(
            f"No ongoing playback resume file found at {resume_path}. Start with an ISO "
            "--playback-start first."
        )
    timestamp = json.loads(resume_path.read_text(encoding="utf-8"))["timestamp"]
    moment = datetime.fromisoformat(timestamp)
    if moment.tzinfo is None:
        raise SystemExit(f"Ongoing playback resume timestamp must include a timezone: {timestamp}")
    return moment


def _write_ongoing_resume(path: str | Path, moment: datetime) -> Path:
    resume_path = Path(path)
    resume_path.parent.mkdir(parents=True, exist_ok=True)
    resume_path.write_text(json.dumps({"timestamp": moment.isoformat()}, indent=2) + "\n")
    return resume_path


def _add_viewer_args(parser) -> None:  # noqa: ANN001
    parser.add_argument(
        "--port",
        type=int,
        default=7000,
        help="Port to serve the viewer on. Keeping it fixed means an already-open tab can "
        "just be refreshed instead of a second one being opened (default: 7000)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Print the URL instead of opening a tab, for when the viewer is restarted "
        "repeatedly. TWIN_LAB_NO_BROWSER=1 does the same for every command",
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="View reusable real stage CAD")
    parser.add_argument("stage_inventory")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--deflection-mm", type=float, default=2.0)
    parser.add_argument(
        "--fps",
        type=float,
        default=30.0,
        help="Animation frame rate; raise for smoother motion (e.g. 120)",
    )
    parser.add_argument(
        "--playback-recording",
        help="JSON file of recorded EPICS commands to recreate (see epics_playback.load_recorded_commands)",
    )
    parser.add_argument(
        "--playback-start",
        help="ISO-8601 start of an archiver time window to replay, e.g. 2026-08-26T15:52:00-07:00 "
        "(needs PCDS network access; alternative to --playback-recording)",
    )
    parser.add_argument(
        "--playback-end",
        help="ISO-8601 end of the archiver time window given by --playback-start, or "
        "'ongoing'/'continuous' to replay forward at 1x until stopped",
    )
    parser.add_argument(
        "--playback-command-map",
        default="config/crystal-stack-command-map.yaml",
        help="Joint-to-PV map used to interpret --playback-recording/--playback-start",
    )
    parser.add_argument(
        "--playback-speed",
        type=float,
        default=1.0,
        help="Playback rate relative to real time, up to the panel slider's 8x (e.g. 0.25 to 8)",
    )
    parser.add_argument(
        "--playback-poll-period-s",
        type=float,
        default=2.0,
        help="How often --playback-end ongoing/continuous extends its archive query",
    )
    parser.add_argument(
        "--playback-lookahead-s",
        type=float,
        default=8.0,
        help="How far ahead of the continuous playback clock to buffer archived commands",
    )
    parser.add_argument(
        "--playback-resume-file",
        default=str(DEFAULT_ONGOING_RESUME_PATH),
        help="Where ongoing playback saves its last archive timestamp; use "
        "--playback-start resume to restart from it",
    )
    parser.add_argument(
        "--pv-names",
        action="store_true",
        help="Label joints by their EPICS PV in the playback readout instead of this repo's "
        "chain/axis naming (e.g. 'POLYCAP:CRY:N:X' instead of 'A050')",
    )
    _add_viewer_args(parser)
    args = parser.parse_args()

    scene = prepare_stage_cad(
        args.stage_inventory,
        rebuild=args.rebuild,
        linear_deflection_mm=args.deflection_mm,
    )
    print(f"Stage CAD cache: {scene.parent}")
    if not args.prepare_only:
        playback = None
        joint_labels = None
        ongoing_playback = False
        if args.playback_recording:
            from .epics_playback import build_playback_from_recording

            playback = build_playback_from_recording(
                args.playback_recording,
                args.playback_command_map,
                args.stage_inventory,
                speed=args.playback_speed,
            )
        elif args.playback_start or args.playback_end:
            if not (args.playback_start and args.playback_end):
                raise SystemExit("--playback-start and --playback-end must be given together")
            if _is_ongoing_playback_end(args.playback_end):
                if args.playback_speed != 1.0:
                    raise SystemExit(
                        "--playback-speed is only for finite playback; ongoing playback always "
                        "runs at 1x"
                    )
                from .epics_playback import build_ongoing_playback_from_archive

                ongoing_playback = True
                start = (
                    _load_ongoing_resume_start(args.playback_resume_file)
                    if _is_ongoing_playback_resume_start(args.playback_start)
                    else datetime.fromisoformat(args.playback_start)
                )
                playback = build_ongoing_playback_from_archive(
                    start,
                    args.playback_command_map,
                    args.stage_inventory,
                    poll_period_s=args.playback_poll_period_s,
                    lookahead_s=args.playback_lookahead_s,
                )
            else:
                from .epics_playback import build_playback_from_archive

                start = datetime.fromisoformat(args.playback_start)
                playback = build_playback_from_archive(
                    start,
                    datetime.fromisoformat(args.playback_end),
                    args.playback_command_map,
                    args.stage_inventory,
                    speed=args.playback_speed,
                )
        if playback is not None and args.pv_names:
            joint_labels = _pv_name_labels(args.playback_command_map)
        try:
            view_stage_cad(
                scene,
                fps=args.fps,
                playback=playback,
                joint_labels=joint_labels,
                port=args.port,
                open_browser=not args.no_browser,
            )
        except KeyboardInterrupt:
            print("\nStage CAD viewer stopped.")
        finally:
            if ongoing_playback and playback is not None:
                current_moment = playback.current_moment()
                if hasattr(playback, "close"):
                    playback.close()
                resume_path = _write_ongoing_resume(
                    args.playback_resume_file, current_moment
                )
                print(
                    "Ongoing playback resume saved. To restart this viewer from that point, run:\n"
                    f"  uv run slac-stage-cad {args.stage_inventory} "
                    "--playback-start resume --playback-end ongoing "
                    f"--playback-resume-file {resume_path}"
                )


def main_live() -> None:
    """Entry point for `slac-live-feed`: view-only, mirrors real EPICS commands.

    Two mutually exclusive sources:
    - Direct archiver polling (`--lookback-s`/`--poll-period-s`, default): needs
      `archapp` + PCDS network access.
    - `--live-file PATH`: watches a recording JSON file that something else
      (running wherever archapp *is* available) keeps overwriting - the
      workaround for environments that cannot reach the archiver directly.
    """

    import argparse

    parser = argparse.ArgumentParser(
        description="Mirror real EPICS motor commands live during an experiment run"
    )
    parser.add_argument("stage_inventory")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--deflection-mm", type=float, default=2.0)
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--command-map", default="config/crystal-stack-command-map.yaml")
    parser.add_argument(
        "--live-file",
        help="Watch this recording JSON file instead of polling the archiver directly "
        "(for environments without archapp/PCDS network access - see "
        "epics_playback.LiveFileSource)",
    )
    parser.add_argument(
        "--lookback-s",
        type=float,
        default=30.0,
        help="How far back each archiver poll looks for the latest command per joint "
        "(ignored with --live-file)",
    )
    parser.add_argument(
        "--poll-period-s",
        type=float,
        default=2.0,
        help="How often to re-poll the archiver, or re-check --live-file's mtime (the "
        "archiver itself trails real hardware by roughly this much already, so shorter "
        "than ~1-2s buys little)",
    )
    parser.add_argument(
        "--pv-names",
        action="store_true",
        help="Label joints by their EPICS PV in the playback readout instead of this repo's "
        "chain/axis naming (e.g. 'POLYCAP:CRY:N:X' instead of 'A050')",
    )
    _add_viewer_args(parser)
    args = parser.parse_args()

    scene = prepare_stage_cad(
        args.stage_inventory, rebuild=args.rebuild, linear_deflection_mm=args.deflection_mm
    )
    print(f"Stage CAD cache: {scene.parent}")
    if args.live_file:
        from .epics_playback import build_live_file_source

        live = build_live_file_source(
            args.live_file, args.command_map, args.stage_inventory, poll_period_s=args.poll_period_s
        )
        print(f"Watching {args.live_file} for updates every {args.poll_period_s}s.")
    else:
        from .epics_playback import build_live_source

        live = build_live_source(
            args.command_map,
            args.stage_inventory,
            lookback_s=args.lookback_s,
            poll_period_s=args.poll_period_s,
        )
    joint_labels = _pv_name_labels(args.command_map) if args.pv_names else None
    try:
        view_stage_cad(
            scene,
            fps=args.fps,
            playback=live,
            joint_labels=joint_labels,
            port=args.port,
            open_browser=not args.no_browser,
        )
    except KeyboardInterrupt:
        print("\nLive feed viewer stopped.")


if __name__ == "__main__":
    main()
