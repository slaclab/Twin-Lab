"""Unified viewer where manual sliders drive both the render and clearance reporting.

The stage-CAD viewer computes poses by hand for speed. This viewer instead drives
a Drake plant compiled from the same reviewed inventory, so the geometry on screen
and the geometry being checked for interference are the same kinematics.
"""

from __future__ import annotations

import csv
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import numpy as np

from .collision import CollisionModel, part_of
from .meshcat_ui import FRAMING_DISTANCE, ISOMETRIC_DIRECTION
from .paths import CACHE_ROOT, EXPORT_ROOT, resolve_repo_path, review_artifact_stem

WARN_LABEL = "Clearance warning band (mm)"
AUTO_RANGE_LABEL = "Auto motion range (% of travel)"
AUTO_PERIOD_LABEL = "Auto motion period (s)"
# Drake can publish a slider but not a checkbox, so the on/off controls step 0 to 1 and
# meshcat_ui.TOGGLE_JS swaps a real checkbox into their row.
COLLISION_LABEL = "Collision detection"
ANIMATION_LABEL = "Animation"
ISOLATE_LABEL = "Isolate worst pair"
# A hull encloses its part, so the CAD re-check can only ever open a reported gap. That is
# what makes it safe to fold into the live reading rather than leave it as a review step.
# No apostrophes; Drake evals control names.
VERIFY_LABEL = "Verify against CAD"
ISOMETRIC_LABEL = "Isometric view"
STATUS_RGB = {
    "clear": [0.13, 0.42, 0.18],
    "close": [0.72, 0.60, 0.05],
    "interference": [0.60, 0.08, 0.08],
}
# Off while the parts themselves carry the state; the tint fought the highlight colours.
PAINT_STATUS_BACKGROUND = False
# Highlights sit on top of the reviewed colours, so they are saturated rather than tinted.
# They must be fully opaque: three.js draws translucent meshes in a depth-sorted pass, so a
# translucent highlight inside the translucent enclosure appears or vanishes with the camera.
HIGHLIGHT_RGBA = {
    "close": (1.0, 0.80, 0.0, 1.0),
    "interference": (0.95, 0.10, 0.10, 1.0),
}
# Drake's MeshcatVisualizer publishes each body at this prefix, with "::" written as "/".
VISUALIZER_PREFIX = "/drake/visualizer"
# Highlights hang under the body they belong to, so they follow it without per-frame updates.
HIGHLIGHT_GROUP = "clearance"
# Drake's own sky gradient, restored when clearance checking is switched off.
DEFAULT_TOP_RGB = [0.53, 0.81, 0.98]
DEFAULT_BOTTOM_RGB = [0.10, 0.10, 0.44]
OFFENDER_LIMIT = 12
# The signed-distance query costs ~30 ms, so running it every animated frame would cap the
# loop near 30 fps; throttle it to this rate so the render can reach the requested fps.
DETECTOR_HZ = 20.0
# Measuring the tessellated parts costs 5-240 ms a pair, far too much to drag a slider
# through. It waits for the pose to hold still this long; until then the reading is the
# hull distance with only the proudness correction, which errs towards reporting contact.
VERIFY_SETTLE_S = 0.3


@dataclass(frozen=True)
class SliderJoint:
    """One SDF joint presented in millimetres or degrees around its logical home."""

    joint_name: str
    stack: str
    stage_ref: str
    joint_type: str
    sdf_lower: float
    sdf_upper: float
    logical_offset: float
    reviewed_home: float

    @property
    def scale(self) -> float:
        return 1000.0 if self.joint_type == "prismatic" else 180.0 / math.pi

    @property
    def unit(self) -> str:
        return "mm" if self.joint_type == "prismatic" else "deg"

    @property
    def label(self) -> str:
        return f"{self.stack} / {self.stage_ref} {self.joint_name} ({self.unit})"

    def to_sdf(self, slider_value: float) -> float:
        return slider_value / self.scale - self.logical_offset

    def slider_bounds(self) -> tuple[float, float, float]:
        lower = (self.sdf_lower + self.logical_offset) * self.scale
        upper = (self.sdf_upper + self.logical_offset) * self.scale
        return lower, upper, self.reviewed_home * self.scale


def read_joint_metadata(package_dir: Path) -> list[SliderJoint]:
    """Read the compiled joint table so sliders match the reviewed operating window."""

    with (package_dir / "joint_metadata.csv").open(encoding="utf-8") as stream:
        return [
            SliderJoint(
                joint_name=row["joint_name"],
                stack=row["stack"],
                stage_ref=row["stage_ref"],
                joint_type=row["type"],
                sdf_lower=float(row["sdf_lower"]),
                sdf_upper=float(row["sdf_upper"]),
                logical_offset=float(row["logical_home_offset"]),
                reviewed_home=float(row["reviewed_home"]),
            )
            for row in csv.DictReader(stream)
        ]


def run_collision_viewer(
    package_dir: str | Path,
    *,
    warn_mm: float = 5.0,
    ignore_file: str | Path | None = None,
    label_source: str | Path | None = None,
    decomposition_dir: str | Path | None = None,
    fps: float = 30.0,
) -> None:
    """Drive the compiled assembly from sliders and report clearance at every pose."""

    from pydrake.geometry import Meshcat

    from .meshcat_ui import (
        announce_viewer,
        patch_meshcat_page,
        print_view_help,
        viewer_params,
    )
    from .scene import load_scene

    package = Path(package_dir).resolve()
    sdf_path = next(
        path for path in sorted(package.glob("*.sdf")) if not path.stem.endswith("_matlab")
    )
    joints = read_joint_metadata(package)

    # Nothing here publishes a realtime rate, so the stats plot only ever covers the view.
    patch_meshcat_page()
    meshcat = Meshcat(viewer_params())

    announce_viewer("Collision viewer", meshcat)
    print(f"Model: {sdf_path}")
    print("Loading collision geometry into Drake; the viewer stays blank until this finishes.")
    load_start = time.monotonic()
    scene = load_scene(sdf_path, meshcat=meshcat)
    model = CollisionModel(
        scene,
        _read_ignored(ignore_file),
        _read_part_labels(label_source),
        decomposition_dir,
    )
    print(
        f"Loaded {_proximity_geometry_count(model)} collision geometries "
        f"in {time.monotonic() - load_start:.0f} s"
    )
    print(
        f"Reopened the surroundings of {model.reopened_joints} joints that Drake's "
        "joint-adjacency filter had hidden from the static environment."
    )

    for joint in joints:
        lower, upper, home = joint.slider_bounds()
        meshcat.AddSlider(joint.label, lower, upper, 0.05, home)
    # Panel order: the two clearance toggles sit together above the band they act on, then
    # the animation toggle above the motion it drives. CONTROLS_JS drops the zoom-limit
    # toggle in behind ANIMATION_LABEL.
    meshcat.AddSlider(COLLISION_LABEL, 0.0, 1.0, 1.0, 1.0)
    meshcat.AddSlider(ISOLATE_LABEL, 0.0, 1.0, 1.0, 0.0)
    if model.refiner is not None:
        meshcat.AddSlider(VERIFY_LABEL, 0.0, 1.0, 1.0, 1.0)
    meshcat.AddSlider(WARN_LABEL, 0.0, 50.0, 0.5, warn_mm)
    meshcat.AddSlider(ANIMATION_LABEL, 0.0, 1.0, 1.0, 0.0)
    meshcat.AddSlider(AUTO_RANGE_LABEL, 0.0, 100.0, 1.0, 25.0)
    meshcat.AddSlider(AUTO_PERIOD_LABEL, 2.0, 60.0, 0.5, 12.0)
    meshcat.AddButton("Reset to home")
    meshcat.AddButton(ISOMETRIC_LABEL)
    meshcat.AddButton("Log clearance report")
    meshcat.AddButton("Stop viewer", "Escape")
    highlighter = _Highlighter(meshcat, model)

    print(f"{len(joints)} joints")
    print("Offending parts light up: YELLOW inside the warning band, RED where they touch.")
    print("Clear 'Collision detection' to turn checking off and use this as a plain viewer.")
    print("Tick 'Isolate worst pair' to hide the assembly and leave only that pair on screen.")
    print("Tick 'Animation' to cycle every joint about its reviewed home.")
    print(f"'{ISOMETRIC_LABEL}' frames the whole assembly down the corner diagonal.")
    if model.refiner is not None:
        print(
            f"'{VERIFY_LABEL}' re-checks every reported pair against the CAD behind the hulls "
            "and reports the corrected distance; it can only open a gap, never close one."
        )
    print_view_help()
    print("Press Escape in Meshcat or Ctrl-C here to stop.")

    frame_period = 1.0 / max(fps, 1.0)
    detector_period = 1.0 / DETECTOR_HZ
    reset_clicks = 0
    isometric_clicks = 0
    log_clicks = 0
    collision_on = True
    animating = False
    show_all = True
    phase = 0.0
    previous_tick = time.monotonic()
    previous_pose: tuple[list[float], float, bool] | None = None
    previous_status: str | None = None
    readout: list[str] = []
    previous_summary = ""
    last_detect = 0.0
    settled_at = 0.0
    mesh_pending = False
    while meshcat.GetButtonClicks("Stop viewer") == 0:
        tick = time.monotonic()
        elapsed = tick - previous_tick
        previous_tick = tick

        wanted_collision = meshcat.GetSliderValue(COLLISION_LABEL) >= 0.5
        wanted_animating = meshcat.GetSliderValue(ANIMATION_LABEL) >= 0.5
        wanted_show_all = meshcat.GetSliderValue(ISOLATE_LABEL) < 0.5
        new_reset = meshcat.GetButtonClicks("Reset to home")
        if new_reset != reset_clicks:
            reset_clicks = new_reset
            wanted_animating = False
            meshcat.SetSliderValue(ANIMATION_LABEL, 0.0)
            phase = 0.0
            for joint in joints:
                meshcat.SetSliderValue(joint.label, joint.slider_bounds()[2])

        new_isometric = meshcat.GetButtonClicks(ISOMETRIC_LABEL)
        if new_isometric != isometric_clicks:
            isometric_clicks = new_isometric
            _look_isometric(meshcat, model)

        if (wanted_collision, wanted_animating, wanted_show_all) != (
            collision_on,
            animating,
            show_all,
        ):
            if wanted_collision != collision_on:
                print(f"Collision detection {'ON' if wanted_collision else 'OFF'}.")
            if not wanted_collision:
                _reset_status(meshcat)
                highlighter.clear()
                readout = _clear_readout(meshcat, readout)
            if not wanted_collision or wanted_show_all:
                highlighter.isolate(False)
            collision_on, animating, show_all = (
                wanted_collision,
                wanted_animating,
                wanted_show_all,
            )
            previous_pose = None
            previous_status = None
            previous_summary = ""

        if animating:
            period = max(meshcat.GetSliderValue(AUTO_PERIOD_LABEL), 0.1)
            span_fraction = meshcat.GetSliderValue(AUTO_RANGE_LABEL) / 100.0
            phase = math.fmod(phase + 2.0 * math.pi * elapsed / period, 2.0 * math.pi)
            for index, joint in enumerate(joints):
                lower, upper, home = joint.slider_bounds()
                amplitude = max(min(home - lower, upper - home), 0.0) * span_fraction
                offset = 2.0 * math.pi * index / max(len(joints), 1)
                meshcat.SetSliderValue(joint.label, home + amplitude * math.sin(phase + offset))

        values = [meshcat.GetSliderValue(joint.label) for joint in joints]
        warn_m = max(meshcat.GetSliderValue(WARN_LABEL), 0.0) / 1000.0
        verify_on = model.refiner is not None and meshcat.GetSliderValue(VERIFY_LABEL) >= 0.5
        new_log = meshcat.GetButtonClicks("Log clearance report")
        asked = new_log != log_clicks
        pose = (values, warn_m, verify_on)
        moved = pose != previous_pose
        if moved:
            previous_pose = pose
            settled_at = tick + VERIFY_SETTLE_S
            mesh_pending = verify_on and collision_on
        mesh_due = mesh_pending and not animating and tick >= settled_at
        if moved or asked or mesh_due:
            model.set_positions(
                {
                    joint.joint_name: joint.to_sdf(value)
                    for joint, value in zip(joints, values, strict=True)
                }
            )
            scene.diagram.ForcedPublish(model.context)
            # The render above runs every frame; the query below is throttled so its cost
            # stutters the detector rather than the motion.
            detect_due = not animating or asked or tick - last_detect >= detector_period
            if collision_on and detect_due:
                last_detect = tick
                report = model.report(warn_m=warn_m)
                refinements = ()
                if verify_on:
                    with_mesh = mesh_due or asked
                    mesh_pending = not with_mesh
                    report, refinements = model.verify(
                        report, limit=OFFENDER_LIMIT, with_mesh=with_mesh
                    )
                if report.status != previous_status:
                    previous_status = report.status
                    _set_status(meshcat, report.status)
                selected = None if show_all else _isolated_parts(report)
                highlighter.isolate(selected is not None)
                highlighter.update(report, selected)
                readout = _set_offender_readout(meshcat, report, readout, show_all=show_all)
                if new_log != log_clicks:
                    log_clicks = new_log
                    _print_report(report)
                    _print_refinements(refinements)
                elif report.summary() != previous_summary:
                    previous_summary = report.summary()
                    print(report.summary())
            elif not collision_on:
                log_clicks = new_log
        frame_cost = time.monotonic() - tick
        time.sleep(max(0.0, frame_period - frame_cost) if animating else 0.1)


def _reset_status(meshcat) -> None:
    if not PAINT_STATUS_BACKGROUND:
        return
    meshcat.SetProperty("/Background/<object>", "top_color", DEFAULT_TOP_RGB)
    meshcat.SetProperty("/Background/<object>", "bottom_color", DEFAULT_BOTTOM_RGB)


class _Highlighter:
    """Repaints the offending collision hulls so the reported pair is findable on screen.

    The hulls are what Drake actually tests, and they wrap the reviewed part, so drawing
    them over the illustration mesh marks the part without splitting its visual geometry.
    """

    def __init__(self, meshcat, model: CollisionModel):
        from pydrake.geometry import Role

        self._meshcat = meshcat
        inspector = _inspector(model)
        self._geometries = {}
        for geometry_id in inspector.GetAllGeometryIds(Role.kProximity):
            frame_path = inspector.GetName(inspector.GetFrameId(geometry_id)).replace("::", "/")
            leaf = inspector.GetName(geometry_id).replace("::", "_")
            self._geometries[model.scene.geometry_name(inspector, geometry_id)] = (
                f"{VISUALIZER_PREFIX}/{frame_path}/{HIGHLIGHT_GROUP}/{leaf}",
                inspector.GetShape(geometry_id),
                inspector.GetPoseInFrame(geometry_id),
            )
        self._visuals: list[str] = []
        for geometry_id in inspector.GetAllGeometryIds(Role.kIllustration):
            frame_path = inspector.GetName(inspector.GetFrameId(geometry_id)).replace("::", "/")
            # Drake publishes the scoped geometry name as further path levels, not one leaf.
            leaf = inspector.GetName(geometry_id).replace("::", "/")
            self._visuals.append(f"{VISUALIZER_PREFIX}/{frame_path}/{leaf}")
        self._shown: dict[str, str] = {}
        self._uploaded: dict[str, str] = {}
        self._hidden: frozenset[str] = frozenset()

    def _paint(self, name: str, state: str) -> str:
        """Upload a hull only when its colour is wrong; uploads cost ~3 ms each."""

        from pydrake.geometry import Rgba

        path, shape, pose = self._geometries[name]
        if self._uploaded.get(name) != state:
            self._meshcat.SetObject(path, shape, Rgba(*HIGHLIGHT_RGBA[state]))
            self._meshcat.SetTransform(path, pose)
            self._uploaded[name] = state
        return path

    def update(self, report, parts: frozenset[str] | None = None) -> None:
        """Light up every offending hull, or only those of ``parts`` when given."""

        wanted = {
            name: state
            for name, state in report.geometry_states().items()
            if name in self._geometries and (parts is None or part_of(name) in parts)
        }
        for name in self._shown.keys() - wanted.keys():
            self._meshcat.SetProperty(self._geometries[name][0], "visible", False)
        for name, state in wanted.items():
            path = self._paint(name, state)
            if name not in self._shown:
                self._meshcat.SetProperty(path, "visible", True)
        self._shown = wanted

    def isolate(self, isolated: bool) -> None:
        """Drop the illustration meshes so only the highlighted hulls are left on screen.

        The compiled visuals are one mesh per sub-assembly OBJ, not per reviewed part, so
        hiding them all and leaving the per-part hulls is the only exact way to isolate.
        """

        hidden = frozenset(self._visuals) if isolated else frozenset()
        for path in hidden - self._hidden:
            self._meshcat.SetProperty(path, "visible", False)
        for path in self._hidden - hidden:
            self._meshcat.SetProperty(path, "visible", True)
        self._hidden = hidden

    def clear(self) -> None:
        for name in self._shown:
            self._meshcat.SetProperty(self._geometries[name][0], "visible", False)
        self._shown = {}


def _set_status(meshcat, status: str) -> None:
    """Paint the whole viewport by clearance state so the pose is readable at a glance."""

    print(status.upper())
    if not PAINT_STATUS_BACKGROUND:
        return
    color = STATUS_RGB[status]
    # Meshcat wants the property on the Background's object, not the group path.
    meshcat.SetProperty("/Background/<object>", "top_color", color)
    meshcat.SetProperty("/Background/<object>", "bottom_color", color)


def _isolated_parts(report) -> frozenset[str] | None:
    """The worst offending pair, or the whole assembly when nothing is inside the band."""

    worst = report.offenders(1)
    return frozenset(worst[0].parts) if worst else None


def _offender_labels(report, limit: int) -> list[str]:
    """Name the worst part pairs as Meshcat control labels, worst first.

    Each label carries its own state: a pose can hold one pair in contact while the rest of
    the list is merely inside the band, and calling those TOUCHING too made the readout
    disagree with the highlights on screen.

    Distances are deliberately left out so the labels only change when the offending
    pairs change; a live number would rebuild the controls on every slider step.
    """

    if report.status == "clear":
        return [f"clear: nothing within {report.warn_m * 1000:.0f} mm"]
    labels = []
    counts = {"TOUCHING": 0, "CLOSE": 0}
    for item in report.offenders(limit):
        heading = "TOUCHING" if item.distance_m <= 0.0 else "CLOSE"
        counts[heading] += 1
        first, second = report.labeled_parts(item)
        labels.append(f"{heading} {counts[heading]}: {first} <-> {second}")
    hidden = len(report.touching_pairs) + len(report.warning_pairs) - len(labels)
    if hidden > 0:
        # No apostrophes: Drake builds each control's JS callback by pasting the name into
        # a single-quoted string literal and eval-ing it, so a quote drops the control.
        labels.append(f"+{hidden} more part pairs (see Log clearance report)")
    return labels


def _set_offender_readout(meshcat, report, previous: list[str], *, show_all: bool) -> list[str]:
    """Republish the offending part IDs as buttons, the only text Meshcat can show."""

    labels = _offender_labels(report, OFFENDER_LIMIT if show_all else 1)
    if labels == previous:
        return previous
    _clear_readout(meshcat, previous)
    for name in labels:
        meshcat.AddButton(name)
    return labels


def _clear_readout(meshcat, previous: list[str]) -> list[str]:
    for name in previous:
        meshcat.DeleteButton(name)
    return []


def _read_ignored(ignore_file: str | Path | None) -> frozenset[tuple[str, str]]:
    if ignore_file is None:
        return frozenset()
    from .collision import read_ignored_pairs

    return read_ignored_pairs(ignore_file)


def _read_part_labels(label_source: str | Path | None) -> dict[str, str]:
    if label_source is None:
        return {}
    from .collision import read_part_labels

    return read_part_labels(label_source)


def _needs_recompile(package_dir: Path, scene_path: Path, collision_mode: str) -> bool:
    """Recompile whenever the package no longer matches the scene meshes and review settings."""

    from .sdf_compiler import package_is_current

    return not package_is_current(
        package_dir,
        scene_path,
        include_collisions=True,
        collision_mode=collision_mode,
        neutral_visuals=True,
    )


def _query_object(model: CollisionModel):
    from pydrake.geometry import QueryObject

    scene_context = model.scene.scene_graph.GetMyContextFromRoot(model.context)
    return cast(QueryObject, model.scene.scene_graph.get_query_output_port().Eval(scene_context))


def _inspector(model: CollisionModel):
    return _query_object(model).inspector()


def isometric_camera(lower: np.ndarray, upper: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Where to stand, and what to look at, to photograph a box isometrically.

    The target is the centre of the box and the camera sits back along
    ``ISOMETRIC_DIRECTION``, far enough out that a sphere around the box is still in frame.
    """
    lower = np.asarray(lower, dtype=float)
    upper = np.asarray(upper, dtype=float)
    target = (lower + upper) / 2.0
    # A degenerate box would put the camera inside its own subject, so keep a floor on the
    # radius; the value only has to be small next to anything worth photographing.
    radius = max(float(np.linalg.norm(upper - lower)) / 2.0, 1e-3)
    direction = np.asarray(ISOMETRIC_DIRECTION, dtype=float)
    direction = direction / np.linalg.norm(direction)
    return target + direction * radius * FRAMING_DISTANCE, target


def _assembly_bounds(model: CollisionModel) -> tuple[np.ndarray, np.ndarray] | None:
    """The world-frame bounding box of everything the plant collides with, or ``None``.

    The compiled package bakes each part's transform into its hull meshes rather than
    carrying a per-geometry pose, so the geometry origins all collapse onto a handful of
    link frames and say nothing about how far the assembly reaches. The extents have to
    come from the meshes. Asking a convex-declared geometry for its convex hull hands back
    the mesh Drake already loaded, which makes this cheap enough to run on a click.
    """
    from pydrake.geometry import Role

    query = _query_object(model)
    inspector = query.inspector()
    lower = np.full(3, np.inf)
    upper = np.full(3, -np.inf)
    for geometry_id in inspector.GetAllGeometryIds(Role.kProximity):
        shape = inspector.GetShape(geometry_id)
        if not hasattr(shape, "GetConvexHull"):
            continue
        box_lower, box_upper = shape.GetConvexHull().CalcBoundingBox()
        # Rotating an axis-aligned box does not leave it axis-aligned, so carry all eight
        # corners across rather than just the two. The result is loose on a tilted part,
        # which only ever frames a little wider than needed.
        corners = np.array(
            [
                [box_lower[0], box_upper[0]],
                [box_lower[1], box_upper[1]],
                [box_lower[2], box_upper[2]],
            ]
        )
        grid = np.array(np.meshgrid(*corners)).reshape(3, -1)
        pose = query.GetPoseInWorld(geometry_id)
        world = pose.rotation().matrix() @ grid + pose.translation().reshape(3, 1)
        lower = np.minimum(lower, world.min(axis=1))
        upper = np.maximum(upper, world.max(axis=1))
    return None if not np.isfinite(lower).all() else (lower, upper)


def _look_isometric(meshcat, model: CollisionModel) -> None:
    """Point the camera at the whole assembly from the corner diagonal."""
    bounds = _assembly_bounds(model)
    if bounds is None:
        print("Nothing to frame: the plant has no collision geometry.")
        return
    camera, target = isometric_camera(*bounds)
    meshcat.SetCameraPose(camera, target)


def _proximity_geometry_count(model: CollisionModel) -> int:
    from pydrake.geometry import Role

    return _inspector(model).NumGeometriesWithRole(Role.kProximity)


def _print_report(report) -> None:
    print(f"\n--- clearance report ({report.warn_m * 1000:.1f} mm band) ---")
    if not report.clearances:
        print("  nothing within the warning band")
    for item in report.clearances[:25]:
        state = "TOUCH" if item.distance_m <= 0.0 else "close"
        first, second = report.described(item)
        part_a, part_b = report.labeled_parts(item)
        print(
            f"  {state} {item.distance_m * 1000:+8.2f} mm  {part_a} <-> {part_b}"
            f"   ({first}  <->  {second})"
        )
    print(
        f"  {len(report.touching_pairs)} part pairs touching, "
        f"{len(report.warning_pairs)} more within band, "
        f"{len(report.clearances)} hull pairs reported"
    )


def _print_refinements(refinements) -> None:
    """Print what the CAD re-check found behind the hulls of each reported pair."""

    if not refinements:
        return
    print("\n--- CAD re-check ---")
    for refinement in refinements:
        print(f"  {refinement.describe()}")
    print(
        "  'explained' means the overlap fits inside the decomposition error and the CAD "
        "underneath is clear; it is evidence for review, not a clearance measurement."
    )


def main() -> None:
    import argparse

    from .sdf_compiler import compile_sdf_package
    from .stage_cad_viewer import prepare_stage_cad

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage_inventory")
    parser.add_argument("--package-dir", type=Path)
    parser.add_argument("--warn-mm", type=float, default=5.0)
    parser.add_argument(
        "--ignore-file",
        type=Path,
        help="YAML holding an `ignored_pairs` block; defaults to the stage inventory itself",
    )
    parser.add_argument(
        "--collision-mode",
        choices=("hull", "convex"),
        default="convex",
        help="convex runs CoACD once and caches it; hull is fast but overestimates volume",
    )
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument(
        "--decomposition-workers",
        type=int,
        default=None,
        help="Parallel CoACD workers for the one-time convex build",
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=30.0,
        help="Animation frame rate; raise for smoother motion (e.g. 120)",
    )
    args = parser.parse_args()

    inventory = resolve_repo_path(args.stage_inventory).resolve()
    scene_path = prepare_stage_cad(inventory, rebuild=args.rebuild)
    package_dir = args.package_dir or EXPORT_ROOT / f"{review_artifact_stem(inventory)}.collision"
    if args.rebuild or _needs_recompile(package_dir, scene_path, args.collision_mode):
        print(f"Compiling collision package into {package_dir}")
        compile_sdf_package(
            scene_path,
            package_dir,
            include_collisions=True,
            collision_mode=args.collision_mode,
            neutral_visuals=True,
            decomposition_workers=args.decomposition_workers,
            archive=False,
        )
    # Same directory sdf_compiler decomposed into, so the re-check reads the very hulls
    # that produced the contact rather than a re-run of CoACD.
    decomposition_dir = CACHE_ROOT / "convex-collision" / scene_path.parent.name
    try:
        run_collision_viewer(
            package_dir,
            warn_mm=args.warn_mm,
            ignore_file=args.ignore_file or inventory,
            label_source=inventory,
            decomposition_dir=decomposition_dir if decomposition_dir.is_dir() else None,
            fps=args.fps,
        )
    except KeyboardInterrupt:
        print("\nCollision viewer stopped.")


if __name__ == "__main__":
    main()
