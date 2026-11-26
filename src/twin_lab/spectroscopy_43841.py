"""Offline Bragg preview for the three polycapillary paths of 43841."""

import argparse
import logging
import math
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from contextlib import ExitStack
from dataclasses import dataclass
from functools import lru_cache, partial
from multiprocessing import get_context
from pathlib import Path
from threading import Event
from typing import Any

import numpy as np
import yaml
from pydrake.geometry import Meshcat, Rgba
from pydrake.math import RigidTransform

from .beam import (
    Plane,
    face_from_cache,
    manifest_rotation,
    manifest_transform,
    perpendicular_basis,
    read_beam_config,
)
from .collision import ClearanceReport, CollisionModel
from .collision_artifacts import resolve_runtime
from .collision_viewer import SliderJoint, read_joint_metadata
from .convex_collision import read_obj_parts
from .epics_playback import sdf_joint_name
from .paths import resolve_repo_path
from .spectroscopy import (
    ACTIVE_SIZE_M,
    Array,
    CrystalTrace,
    Detector,
    ReflectionPreset,
    bragg_angle,
    cubic_reflection,
)
from .spectroscopy import (
    LINES as COMMON_LINES,
)
from .spectroscopy_align import AlignmentAxis, AlignmentRig, ClearanceSearch
from .spectroscopy_view import (
    COLORS,
    CheckPose,
    InterferencePreview,
    SpectroscopyPreview,
    detector_panel,
    spectroscopy_page,
)
from .stage_cad_viewer import (
    _add_viewer_args,
    _slider_label,
    _slider_scale,
    joint_transform,
    prepare_stage_cad,
    view_stage_cad,
)

ROOT = "/43841-spectroscopy"
PAPER = "https://doi.org/10.1021/photonsci.5c00024"
LINES = (("Pt L\u03b1 (L\u03b11)", 9442.3), ("Fe K\u03b1 (K\u03b11)", 6403.84), *COMMON_LINES)
DEFAULT_HALF_WIDTH_DEG = 0.1
# Millimetres of spot motion per millimetre of positive LX10 travel, in u/v order.
DETECTOR_TARGET_AXES = (("A205", -1), ("A206", 1))
SLIT_CHAINS = ("LJ Detector 1", "LJ Detector 2")
# These towers' grounded hardware is grouped with unrelated fixed parts in the cached OBJ.
SLIT_SUPPORT_REFS = frozenset({
    "P232", "P281", "P282", "P283", "P330", "P331", "P340", "P345", "P346", "P347",
    "P348", "P349", "P350",
})
MODEL_NOTE = (
    "Flat crystals, ideal parallel rays (no polycapillary divergence or transmission model). "
    "The sensor plane is estimated from the ePix100 housing."
)
# The second solid in both reviewed holder designs is a 70 x 30 x 2 mm plate.
# These are its positive-Z face coordinates in the holder's own STEP frame.
PLATE_HALF_SIZE_M = (0.035, 0.015)
PLATE_FRONT_Z_MM = 14.7
MESH_TOLERANCE_M = 1e-6
type Pose = dict[str, float]
type Joint = dict[str, Any]


@dataclass(frozen=True)
class CrystalFace:
    center_m: Array
    axes: Array  # Rows are the local long axis, short axis, and outward normal.
    half_size_m: tuple[float, float]

    @property
    def normal(self) -> Array:
        return self.axes[2]

    def contains(self, points: Array) -> np.ndarray:
        local = (points - self.center_m) @ self.axes[:2].T
        return np.all(np.abs(local) <= self.half_size_m, axis=1)

    def moved(self, pose: Array) -> "CrystalFace":
        rotation = pose[:3, :3]
        return CrystalFace(
            rotation @ self.center_m + pose[:3, 3], self.axes @ rotation.T, self.half_size_m,
        )

    def outline(self) -> tuple[Array, Array]:
        long, short = self.axes[:2] * np.asarray(self.half_size_m)[:, None]
        corners = self.center_m + np.array([
            -long - short, long - short, long + short, -long + short,
        ])
        cross = 0.15 * np.array([long, short])
        return (
            np.vstack((corners, self.center_m - cross)),
            np.vstack((np.roll(corners, -1, axis=0), self.center_m + cross)),
        )


def load_crystal_face(mesh: Path, ref: str, manifest: Path) -> CrystalFace:
    transform = manifest_transform(manifest, ref)
    rotation, origin = transform[:3, :3], transform[:3, 3] / 1000
    center = origin + rotation[:, 2] * (PLATE_FRONT_Z_MM / 1000)
    face = CrystalFace(center, rotation.T, PLATE_HALF_SIZE_M)
    for name, vertices, indices in read_obj_parts(mesh):
        if name != ref:
            continue
        triangles = ((np.asarray(vertices) - center) @ rotation)[indices]
        plane = np.abs(triangles[:, :, 2]) <= MESH_TOLERANCE_M
        bounds = np.asarray(face.half_size_m) + MESH_TOLERANCE_M
        inside = np.all(np.abs(triangles[:, :, :2]) <= bounds, axis=2)
        a, b, c = triangles[np.all(plane & inside, axis=1)].transpose(1, 0, 2)
        areas = np.cross(b - a, c - a)[:, 2] / 2
        expected = 4 * math.prod(face.half_size_m)
        if np.all(areas > 0) and math.isclose(areas.sum(), expected, rel_tol=1e-4):
            return face
    raise ValueError(f"{ref} in {mesh.name}: reviewed 70 x 30 mm crystal front face not found")


def disk_offsets(radius_m: float) -> Array:
    """Uniform-area parallel ray samples on the optic's circular exit aperture."""
    coord = ((np.arange(32) + 0.5) / 16 - 1) * radius_m
    points = np.column_stack([xyz.ravel() for xyz in np.meshgrid(coord, coord)])
    return points[np.linalg.norm(points, axis=1) < radius_m]


def trace_flat(
    source: Plane, crystal: CrystalFace, detector: Detector, offsets: Array,
    theta: float | None, half_width_rad: float, *, aim: bool = False,
) -> CrystalTrace:
    """Clip the collimated beam to the flat analyzer and project accepted rays."""
    direction = source.normal
    dot = float(direction @ crystal.normal)
    incidence_deg = math.degrees(math.asin(min(max(-dot, -1), 1)))
    front = dot < -1e-10
    # Compute the central ray first: it guides alignment even with zero Bragg acceptance.
    distance = float((crystal.center_m - source.origin_m) @ crystal.normal)
    t = distance / dot if abs(dot) > 1e-10 else 0.0
    central = source.origin_m + t * direction
    outgoing = direction - 2 * dot * crystal.normal
    detector_dot = float(outgoing @ detector.normal)
    detector_distance = float((detector.center_m - central) @ detector.normal)
    forwards = detector_dot < -1e-10 and detector_distance < 0
    uv_axes = np.column_stack((detector.u, detector.v))
    empty = np.empty((0, 3))
    aim_uv: Array | None = None
    aim_cost: float | None = None
    axis_uv: Array | None = None
    front_crossing = front and t > 0
    if forwards and (front_crossing or (aim and theta is not None)):
        plane_hit = central + detector_distance / detector_dot * outgoing
        axis_uv = (plane_hit - detector.center_m) @ uv_axes
    geometric_uv = axis_uv if front_crossing else None
    if aim and theta is not None:
        gap = incidence_deg - math.degrees(theta)
        miss_mm = np.linalg.norm(central - crystal.center_m) * 1000
        aim_cost = 900 * gap**2 + 8 * miss_mm**2
        if t <= 0:
            aim_cost += 20_000
        if axis_uv is not None:
            # Keep projections near grazing from dominating the search.
            aim_uv = np.clip(axis_uv, -0.5, 0.5)[None, :]
        else:
            aim_cost += 20_000
    incidence = (incidence_deg, incidence_deg) if front else None
    if not front or theta is None or abs(math.radians(incidence_deg) - theta) > half_width_rad:
        return CrystalTrace(
            incidence, 0, empty, empty[:, :2], np.empty(0), empty, empty, aim_uv, empty, aim_cost,
            geometric_uv_m=geometric_uv,
        )

    basis = np.array(perpendicular_basis(direction))
    start = source.origin_m + offsets @ basis
    distances = ((crystal.center_m - start) @ crystal.normal) / dot
    bounce = start + distances[:, None] * direction
    on_crystal = (distances > 0) & crystal.contains(bounce)
    start, bounce = start[on_crystal], bounce[on_crystal]
    times = (detector.center_m - bounce) @ detector.normal / (
        detector_dot if detector_dot < -1e-10 else 1.0
    )
    forward = (detector_dot < -1e-10) & (times > 0)
    hits = bounce + times[:, None] * outgoing
    uv = (hits - detector.center_m) @ uv_axes
    inside = forward & np.all(np.abs(uv) < ACTIVE_SIZE_M / 2, axis=1)
    preview = np.flatnonzero(inside) if np.any(inside) else np.arange(len(bounce))
    keep = preview[np.linspace(0, len(preview) - 1, min(len(preview), 12), dtype=int)]
    end = bounce + np.where(forward, times, 0.15)[:, None] * outgoing
    return CrystalTrace(
        incidence, len(bounce), hits[inside], uv[inside], np.ones(np.count_nonzero(inside)),
        bounce[keep], end[keep], aim_uv, start[keep], aim_cost,
        geometric_uv_m=geometric_uv,
    )


def chain_pose(chain: Sequence[Joint], positions: Mapping[str, float]) -> Array:
    pose = RigidTransform()
    for joint in chain:
        pose = pose @ joint_transform(joint, positions[joint["key"]])
    return pose.GetAsMatrix4()


@dataclass(frozen=True)
class OpticalPath:
    name: str
    source: Plane
    crystal: CrystalFace
    offsets: Array
    source_chain: tuple[Joint, ...]
    crystal_chain: tuple[Joint, ...]


@dataclass(frozen=True)
class PolycapSpectrometer:
    paths: tuple[OpticalPath, ...]
    detector: Detector
    detector_chain: tuple[Joint, ...]

    # Low-index flat-crystal candidates, not an installed analyzer list. Do not rank
    # the 95835 curved-crystal Fe/Co precedents as confirmed setups for 43841.
    reflections = (
        ReflectionPreset(
            "Graphite(004)", 1.677, "Published PCXS Fe/Pt benchmark", PAPER,
            reference_energies_ev=(9442.3, 6403.84),
        ),
        ReflectionPreset(
            "Graphite(002)", 3.354, "Published PCXS Fe benchmark", PAPER,
            reference_energies_ev=(6403.84,),
        ),
    ) + tuple(
        cubic_reflection(material, hkl)
        for hkl in ((2, 2, 0), (1, 1, 1), (3, 1, 1), (4, 0, 0), (3, 3, 1),
                    (4, 2, 2), (4, 4, 0), (5, 3, 3), (6, 2, 0))
        for material in ("Ge", "Si")
    )
    shortlist_angle_deg = 25.0

    @property
    def crystal_labels(self) -> tuple[str, ...]:
        return tuple(path.name for path in self.paths)

    def rig(self) -> AlignmentRig[Pose]:
        def axis(joint: Joint) -> AlignmentAxis:
            scale, unit = _slider_scale(joint)
            lower, upper = joint["limits"]
            return AlignmentAxis(
                joint["key"], _slider_label(joint, unit), lower * scale, upper * scale,
                lambda value: value * scale,
                lambda value: min(max(value / scale, lower), upper),
            )

        return AlignmentRig(
            tuple(map(axis, self.detector_chain)),
            tuple(
                tuple(map(axis, (*path.source_chain, *path.crystal_chain)))
                for path in self.paths
            ),
            dict.update, dict.copy,
        )

    def clearance_search(
        self, allows: Callable[[Mapping[str, float], Event], bool],
    ) -> ClearanceSearch:
        # Moving the polycapillary stack and outer detector trim can introduce contacts
        # against the fixed chamber even when the ray trace improves.
        sources = {
            joint["key"]: joint["home"] for path in self.paths for joint in path.source_chain
        }
        trims = {key for key, _ in DETECTOR_TARGET_AXES}
        home = {**sources, **{
            joint["key"]: joint["home"] for joint in self.detector_chain if joint["key"] in trims
        }}
        caps = frozenset(sources)
        return ClearanceSearch(
            allows, home, (caps, caps | {"A206"}, caps | trims),
        )

    def trace(
        self, pose: Pose, energy_ev: float, spacing_a: float, order: int, half_width_deg: float,
        *, crystals: Sequence[int] | None = None, aim: bool = False,
    ) -> tuple[float | None, Detector, list[CrystalTrace]]:
        theta = bragg_angle(energy_ev, spacing_a, order)
        if not (math.isfinite(half_width_deg) and 0 < half_width_deg < 90):
            raise ValueError("Bragg half-width must be between 0 and 90 degrees")
        detector = self.detector.moved(chain_pose(self.detector_chain, pose))
        paths = self.paths if crystals is None else tuple(self.paths[i] for i in crystals)
        return theta, detector, [
            trace_flat(
                path.source.transformed(chain_pose(path.source_chain, pose)),
                path.crystal.moved(chain_pose(path.crystal_chain, pose)),
                detector, path.offsets, theta, math.radians(half_width_deg), aim=aim,
            )
            for path in paths
        ]


def housing_detector(
    vertices: Array, rotation: Array,
) -> Detector:
    # P2388 is one housing occurrence, not a separately reviewed chip. Its long
    # local +X points out of the nose; use the nose's bounding plane and center.
    local = vertices @ rotation
    near, far = local.min(axis=0), local.max(axis=0)
    center = (near + far) / 2
    center[0] = far[0]
    normal, u, v = rotation.T
    return Detector(rotation @ center, u, v, normal)


def load_spectrometer(scene_path: Path) -> PolycapSpectrometer:
    scene_path = scene_path.resolve()
    scene = yaml.safe_load(scene_path.read_text(encoding="utf-8"))
    inventory = Path(scene["source_inventory"])
    review = yaml.safe_load(inventory.read_text(encoding="utf-8"))
    if review["subassembly"]["name"] != "DSG-000043841":
        raise ValueError("The polycapillary spectroscopy preview requires the 43841 review")
    manifest = resolve_repo_path(review["cad_manifest"], relative_to=inventory.parent)
    beams = read_beam_config(inventory)
    if {entry["name"] for entry in beams} != {"North", "Middle", "South"} or len(beams) != 3:
        raise ValueError("Expected three reviewed 43841 beam paths")
    chains = {chain["name"]: tuple(chain["joints"]) for chain in scene["motion_chains"]}

    def attachment_chain(mesh: Path, name: str) -> tuple[Joint, ...]:
        chain = chains[name]
        if not any(
            Path(item["mesh"]) == mesh
            and item.get("parent_stage_ref") == chain[-1]["ref"]
            and item.get("parent_joint_key") in (None, chain[-1]["key"])
            for item in scene["attachments"]
        ):
            raise ValueError(f"{mesh.name} is not attached to the end of the reviewed {name} chain")
        return chain

    paths = []
    for entry in sorted(beams, key=lambda entry: ("North", "Middle", "South").index(entry["name"])):
        name = entry["name"]
        source_spec, crystal_spec = entry["source"], entry["crystal"]
        source_mesh = scene_path.parent / source_spec["mesh"]
        crystal_mesh = scene_path.parent / crystal_spec["mesh"]
        source_chain = attachment_chain(source_mesh, f"{name} Polycap")
        crystal_chain = attachment_chain(crystal_mesh, f"{name} Crystal")
        source = face_from_cache(source_mesh, source_spec["ref"], manifest)
        crystal = load_crystal_face(crystal_mesh, crystal_spec["ref"], manifest)
        radius = min(source.radius_m, float(entry["diameter_mm"]) / 2000)
        paths.append(OpticalPath(name, source, crystal, disk_offsets(radius),
                                 source_chain, crystal_chain))

    # Only the detector occurs in all three paths' lists of expected targets.
    common = set.intersection(*(set(entry["expected"]) for entry in beams))
    if len(common) != 1:
        raise ValueError("Expected one shared detector in the reviewed beam paths")
    ref = common.pop()
    detector_ref = chains["Detector"][-1]["ref"]
    candidates = [
        Path(item["mesh"]) for item in scene["attachments"]
        if item.get("style") == "detector" and item["parent_stage_ref"] == detector_ref
    ]
    if len(candidates) != 1:
        raise ValueError("Expected one reviewed detector attachment")
    mesh = candidates[0]
    detector_chain = attachment_chain(mesh, "Detector")
    for name, vertices, _ in read_obj_parts(mesh):
        if name == ref:
            detector = housing_detector(np.array(vertices), manifest_rotation(manifest, ref))
            return PolycapSpectrometer(tuple(paths), detector, detector_chain)
    raise ValueError(f"Reviewed detector {ref} not found in {mesh.name}")


def collision_positions(
    positions: Mapping[str, float], joints: Mapping[str, SliderJoint], hidden: frozenset[str],
) -> dict[str, float]:
    if set(positions) - joints.keys() or joints.keys() - (positions.keys() | hidden):
        raise ValueError("Spectroscopy pose is missing reviewed joints or contains unknown joints")
    return {
        joint.joint_name: positions.get(key, joint.reviewed_home) - joint.logical_offset
        for key, joint in joints.items()
    }


def _build_interference_check(scene_path: Path) -> CheckPose:
    scene = yaml.safe_load(scene_path.read_text(encoding="utf-8"))
    root = resolve_runtime(Path(scene["source_inventory"]))
    package = root / "package"
    metadata = {joint.joint_name: joint for joint in read_joint_metadata(package)}
    by_key = {
        joint["key"]: sdf_joint_name(chain["name"], joint["key"])
        for chain in scene["motion_chains"] for joint in chain["joints"]
    }
    if len(by_key) != len(metadata) or set(by_key.values()) != metadata.keys():
        raise ValueError("Stage CAD does not match the reviewed 43841 collision joints")
    joints = {key: metadata[name] for key, name in by_key.items()}
    hidden = frozenset(
        joint["key"] for chain in scene["motion_chains"] if chain["name"] in SLIT_CHAINS
        for joint in chain["joints"]
    )
    sdf, = (path for path in package.glob("*.sdf") if not path.stem.endswith("_matlab"))
    inventory = root / "review" / "inventory.yaml"
    collision = CollisionModel.load(sdf, ignore_file=inventory, label_source=inventory)
    if set(collision.joint_names()) != metadata.keys():
        raise ValueError("The collision model does not match its reviewed joint metadata")
    collision.set_reviewed_home({
        joint.joint_name: joint.reviewed_home - joint.logical_offset for joint in joints.values()
    })

    def check(positions: Mapping[str, float]) -> ClearanceReport:
        collision.set_positions(collision_positions(positions, joints, hidden))
        return collision.report(warn_m=0.0)

    return check


@lru_cache(maxsize=1)
def _load_interference_check(scene_path: Path) -> CheckPose | None:
    try:
        return _build_interference_check(scene_path)
    except (OSError, ValueError, RuntimeError, KeyError):
        logging.getLogger(__name__).exception("Could not load spectroscopy collision geometry")
        return None


def _check_interference(scene_path: Path, positions: Mapping[str, float]) -> ClearanceReport | None:
    check = _load_interference_check(scene_path)
    return None if check is None else check(positions)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage_inventory")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--deflection-mm", type=float, default=2.0)
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--once", action="store_true", help="Publish one optical frame and exit")
    _add_viewer_args(parser)
    args = parser.parse_args()
    print("Preparing or loading reviewed stage CAD for 43841…", flush=True)
    scene = prepare_stage_cad(
        args.stage_inventory, rebuild=args.rebuild, linear_deflection_mm=args.deflection_mm,
    )
    model = load_spectrometer(scene)
    print(f"Stage CAD cache: {scene.parent}")
    if args.prepare_only:
        return
    rig = model.rig()
    html = detector_panel(
        rig, crystal_labels=model.crystal_labels, reflections=model.reflections,
        root=ROOT, model_note=MODEL_NOTE, lines=LINES, focus_goal_mm=None, ray_guides=True,
        target_moves_detector=True, interference=not args.once,
    )
    try:
        with spectroscopy_page(html), ExitStack() as stack:
            def attach(meshcat: Meshcat) -> Callable[[Pose], None]:
                interference = None
                clearance = None
                if not args.once:
                    # Drake can hold the GIL while loading and querying collision geometry.
                    interference = InterferencePreview(
                        meshcat, ROOT, partial(_check_interference, scene),
                        ProcessPoolExecutor(max_workers=1, mp_context=get_context("spawn")),
                    )
                    stack.callback(interference.close)
                    clearance = model.clearance_search(interference.allows)
                preview = SpectroscopyPreview(
                    meshcat, model, rig, root=ROOT, lines=LINES,
                    default_half_width_deg=DEFAULT_HALF_WIDTH_DEG,
                    detector_target_axes=DETECTOR_TARGET_AXES, interference=interference,
                    clearance=clearance,
                )
                stack.callback(preview.close)
                previous: dict[str, tuple[float, ...]] = {}

                def update(positions: Pose) -> None:
                    for path, color in zip(model.paths, COLORS[:len(model.paths)], strict=True):
                        key = tuple(positions[joint["key"]] for joint in path.crystal_chain)
                        if previous.get(path.name) != key:
                            previous[path.name] = key
                            face = path.crystal.moved(chain_pose(path.crystal_chain, positions))
                            start, end = face.outline()
                            marker = f"{ROOT}/Crystal faces/{path.name}"
                            meshcat.SetLineSegments(marker, start.T, end.T, rgba=Rgba(*color, 1))
                            meshcat.SetProperty(f"{marker}/<object>", "material.depthTest", False)
                    preview.update(positions, positions)

                return update

            view_stage_cad(
                scene, fps=args.fps, port=args.port, open_browser=not args.no_browser,
                hidden_chains=SLIT_CHAINS,
                hidden_fixed_parts=SLIT_SUPPORT_REFS,
                spectroscopy=attach, once=args.once,
            )
    except KeyboardInterrupt:
        print("\nSpectroscopy viewer stopped.")


if __name__ == "__main__":
    main()
