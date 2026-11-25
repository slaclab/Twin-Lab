"""Publish a spectroscopy preview through the existing Meshcat connection."""

import json
import logging
import math
import os
import tempfile
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from enum import IntEnum
from pathlib import Path
from queue import Empty, SimpleQueue
from threading import Event

import numpy as np
from pydrake.geometry import Meshcat, Rgba, Sphere
from pydrake.math import RigidTransform

from .meshcat_ui import patch_meshcat_page
from .spectroscopy import (
    ACTIVE_SIZE_M,
    COLS,
    LINES,
    ROWS,
    Array,
    ReflectionPreset,
    Spectrometer,
    bragg_angle,
    detector_image,
)
from .spectroscopy_align import (
    MIN_SIGNAL_HITS,
    STARTING_POSE_LIMIT,
    AlignmentRequest,
    AlignmentResult,
    AlignmentRig,
    StartingPose,
    find_alignment,
    find_starting_poses,
)
from .spectroscopy_plan import CAPTURE_GOAL, MAX_OFFSET_EV, compare_reflections

LINE = "Emission preset"
REFLECTION = "Crystal preset"
ENERGY = "Custom emission energy (eV)"
SPACING = "Custom d-spacing (angstrom)"
ORDER = "Custom Bragg order"
WIDTH = "Bragg half-width (degrees)"
COLORS = ((0.15, 0.82, 0.96), (0.28, 0.91, 0.38), (0.95, 0.50, 0.87), (0.99, 0.62, 0.25))
ALIGN = "Preview simulated alignment"
SEARCH = "Search simulated starting poses"
CANDIDATE = "Starting pose candidate"
CANCEL = "Cancel simulated alignment"
APPLY = "Apply proposed simulator pose"
COMPARE = "Compare simulated analyzer reflections"
BAND_BELOW = "Band below emission (eV)"
BAND_ABOVE = "Band above emission (eV)"
BAND_DEFAULT = 25.0
TARGET_U = "Alignment target u (mm)"
TARGET_V = "Alignment target v (mm)"
TARGET_STEP_MM = 0.1
TARGET_LIMITS_MM = tuple(
    round((math.ceil(float(half_mm) / TARGET_STEP_MM - 1e-10) - 1) * TARGET_STEP_MM, 1)
    for half_mm in ACTIVE_SIZE_M * 500
)


class AlignmentStatus(IntEnum):
    IDLE = 0
    RUNNING = 1
    READY = 2
    STALE = 3
    NO_IMPROVEMENT = 4
    APPLIED = 5
    FAILED = 6
    SEARCHING = 7
    NO_SIGNAL = 8
    CANCELLING = 9
    CANCELLED = 10


class PlanningStatus(IntEnum):
    IDLE = 0
    READY = 1
    STALE = 2
    FAILED = 3


def detector_panel[PoseT](
    rig: AlignmentRig[PoseT], *, crystal_labels: tuple[str, ...],
    reflections: tuple[ReflectionPreset, ...], root: str, model_note: str,
    lines: tuple[tuple[str, float], ...] = LINES, focus_goal_mm: float | None = 0.5,
) -> str:
    axes = rig.axes
    options = {
        "root": root,
        "modelNote": model_note,
        "crystals": crystal_labels,
        "lineLabel": LINE,
        "reflectionLabel": REFLECTION,
        "energyLabel": ENERGY,
        "spacingLabel": SPACING,
        "orderLabel": ORDER,
        "lines": [*(f"{label} · {energy:.2f} eV" for label, energy in lines), "Custom energy"],
        "reflections": [
            *(f"{preset.label} - {preset.evidence}" for preset in reflections),
            "Custom d-spacing / order",
        ],
        "sizeMm": (ACTIVE_SIZE_M * 1000).tolist(),
        "cols": COLS,
        "rows": ROWS,
        "colors": [
            [round(255 * c) for c in color] for color in COLORS[:len(crystal_labels)]
        ],
        "alignment": {
            "previewLabel": ALIGN,
            "searchLabel": SEARCH,
            "candidateLabel": CANDIDATE,
            "cancelLabel": CANCEL,
            "minSignalHits": MIN_SIGNAL_HITS,
            "startingPoseLimit": STARTING_POSE_LIMIT,
            "focusGoalMm": focus_goal_mm,
            "xFloor": next((axis.lower for axis in axes if axis.key == rig.detector_x), None),
            "applyLabel": APPLY,
            "targetLabels": [TARGET_U, TARGET_V],
            "targetLimitsMm": TARGET_LIMITS_MM,
            "targetStepMm": TARGET_STEP_MM,
            "axes": [axis.label for axis in axes],
            "status": {status.name: status.value for status in AlignmentStatus},
        },
        "planner": {
            "compareLabel": COMPARE,
            "bandLabels": [BAND_BELOW, BAND_ABOVE],
            "maxOffset": MAX_OFFSET_EV,
            "captureGoal": CAPTURE_GOAL,
            "defaultOffset": BAND_DEFAULT,
            "status": {status.name: status.value for status in PlanningStatus},
            "presets": [
                [preset.label, preset.evidence, preset.source_url, preset.published_xcs_band_ev]
                for preset in reflections
            ],
        },
    }
    return (Path(__file__).parent / "assets" / "spectroscopy_panel.html").read_text(
        encoding="utf-8"
    ).replace("__OPTIONS__", json.dumps(options))


@contextmanager
def spectroscopy_page(html: str):
    previous = os.environ.get("DRAKE_RESOURCE_ROOT")
    with tempfile.TemporaryDirectory(prefix="twinlab-spectroscopy-") as directory:
        try:
            patch_meshcat_page(
                extra_html=html, resource_root=Path(directory), show_zoom_override=False,
            )
            yield
        finally:
            if previous is None:
                os.environ.pop("DRAKE_RESOURCE_ROOT", None)
            else:
                os.environ["DRAKE_RESOURCE_ROOT"] = previous


def image_bins(image: Array) -> list[float]:
    flat = image.ravel()
    nonzero = np.flatnonzero(flat)
    if not len(nonzero):
        return []
    return np.column_stack((nonzero, flat[nonzero] / flat[nonzero].max())).ravel().tolist()


class AlignmentPreview[PoseT]:
    def __init__(
        self, meshcat: Meshcat, spectrometer: Spectrometer[PoseT], rig: AlignmentRig[PoseT],
        root: str,
    ):
        self.meshcat = meshcat
        self.spectrometer = spectrometer
        self.rig = rig
        self.root = root
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="spectroscopy-align")
        self.cancel = Event()
        self.future: Future[AlignmentResult | list[StartingPose] | None] | None = None
        self.progress: SimpleQueue[tuple[int, int, int]] = SimpleQueue()
        self.proposal: AlignmentResult | None = None
        self.starting_poses: list[StartingPose] = []
        self.candidate = 0
        self.snapshot: tuple[object, ...] | None = None
        self.clicks = (0, 0, 0, 0)
        meshcat.AddButton(ALIGN)
        meshcat.AddButton(SEARCH)
        meshcat.AddButton(CANCEL)
        meshcat.AddSlider(CANDIDATE, 0, STARTING_POSE_LIMIT - 1, 1, 0)
        meshcat.AddButton(APPLY)
        self.publish(AlignmentStatus.IDLE)

    def publish(self, status: AlignmentStatus, progress: tuple[int, ...] = ()) -> None:
        data = [float(status), *progress]
        if status == AlignmentStatus.READY and self.proposal is not None:
            proposal = self.proposal
            data.extend((len(self.starting_poses), self.candidate))
            for pose in self.starting_poses:
                data.extend((pose.reflection, *pose.alignment.after.signal_rank()))
            data.extend(proposal.detector_target_mm)
            data.extend((float(proposal.x_limit_mm is not None), proposal.x_limit_mm or 0.0))
            data.extend(proposal.start)
            data.extend(proposal.target)
            for frame in (proposal.before, proposal.after):
                if frame.centroid_mm is None or frame.rms_mm is None:
                    data.extend((0, 0, 0, 0))
                else:
                    data.extend(frame.centroid_mm.tolist())
                    data.extend(frame.rms_mm.tolist())
                bins = image_bins(frame.image)
                data.extend((*frame.hits, len(bins)))
                data.extend(bins)
        self.meshcat.SetProperty(self.root, "alignment_frame", data)

    def update(
        self, context: PoseT, positions: dict[str, float], key: tuple[object, ...], *,
        request: AlignmentRequest,
    ) -> None:
        clicks = tuple(
            self.meshcat.GetButtonClicks(label) for label in (ALIGN, SEARCH, APPLY, CANCEL)
        )
        requested, search, apply, cancel = (
            new > old for new, old in zip(clicks, self.clicks, strict=True)
        )
        self.clicks = clicks
        key = (*key, request.target_mm)

        if self.snapshot is not None and key != self.snapshot:
            self.cancel.set()
            self.proposal = None
            self.starting_poses = []
            self.snapshot = None
            if self.future is None:
                self.publish(AlignmentStatus.STALE)
        if cancel and self.future is not None and not self.cancel.is_set():
            self.cancel.set()
            self.publish(AlignmentStatus.CANCELLING)
        if self.future is not None and self.future.done():
            future, self.future = self.future, None
            try:
                result = future.result()
            except (ValueError, RuntimeError):
                logging.getLogger(__name__).exception("Simulated alignment search failed")
                self.snapshot = None
                self.publish(AlignmentStatus.FAILED)
            else:
                if self.snapshot is None:
                    self.publish(AlignmentStatus.STALE)
                elif self.cancel.is_set():
                    self.snapshot = None
                    self.publish(AlignmentStatus.CANCELLED)
                elif isinstance(result, list):
                    if not result:
                        self.publish(AlignmentStatus.NO_SIGNAL)
                    else:
                        self.starting_poses = result
                        self.candidate = 0
                        self.proposal = result[0].alignment
                        self.meshcat.SetSliderValue(CANDIDATE, 0)
                        self.publish(AlignmentStatus.READY)
                elif result is None:
                    self.publish(AlignmentStatus.NO_IMPROVEMENT)
                else:
                    self.proposal = result
                    self.publish(AlignmentStatus.READY)
        elif self.future is not None and not self.cancel.is_set():
            try:
                progress = self.progress.get_nowait()
            except Empty:
                pass
            else:
                self.publish(AlignmentStatus.SEARCHING, progress)
        if (requested or search) and self.future is None:
            if not search and bragg_angle(
                request.energy_ev, request.spacing_a, request.order,
            ) is None:
                return
            self.proposal = None
            self.starting_poses = []
            self.cancel.clear()
            self.snapshot = key
            args = (
                self.rig.clone(context), self.spectrometer, self.rig,
                dict(positions), request, self.cancel,
            )
            self.progress = SimpleQueue()
            if search:
                self.future = self.executor.submit(
                    find_starting_poses, *args, progress=self.progress.put,
                )
            else:
                self.future = self.executor.submit(find_alignment, *args)
            self.publish(AlignmentStatus.SEARCHING if search else AlignmentStatus.RUNNING)
            return
        if self.starting_poses:
            index = int(self.meshcat.GetSliderValue(CANDIDATE))
            if 0 <= index < len(self.starting_poses) and index != self.candidate:
                self.candidate = index
                self.proposal = self.starting_poses[index].alignment
                self.publish(AlignmentStatus.READY)
        if apply and self.snapshot == key and self.proposal is not None:
            for axis, value in zip(self.rig.axes, self.proposal.target, strict=True):
                self.meshcat.SetSliderValue(axis.label, value)
            if self.starting_poses:
                self.meshcat.SetSliderValue(
                    REFLECTION, self.starting_poses[self.candidate].reflection,
                )
            self.proposal = None
            self.starting_poses = []
            self.snapshot = None
            self.publish(AlignmentStatus.APPLIED)

    def close(self) -> None:
        self.cancel.set()
        self.executor.shutdown(wait=True, cancel_futures=True)


class SpectroscopyPreview[PoseT]:
    def __init__(
        self, meshcat: Meshcat, spectrometer: Spectrometer[PoseT], rig: AlignmentRig[PoseT],
        *, root: str, point_source_m: Array | None = None,
        lines: tuple[tuple[str, float], ...] = LINES,
        default_half_width_deg: float = 0.05,
    ):
        self.meshcat = meshcat
        self.spectrometer = spectrometer
        self.root = root
        self.axes = rig.axes
        self.colors = COLORS[:len(spectrometer.crystal_labels)]
        self.reflections = spectrometer.reflections
        self.lines = lines
        for label, low, high, step, initial in (
            (LINE, 0, len(lines), 1, 0),
            (REFLECTION, 0, len(self.reflections), 1, 0),
            (ENERGY, 1000, 25000, 0.1, lines[0][1]),
            (SPACING, 0.3, 5, 0.0001, self.reflections[0].spacing_a),
            (ORDER, 1, 8, 1, 1),
            (WIDTH, 0.025, 1, 0.005, default_half_width_deg),
        ):
            meshcat.AddSlider(label, low, high, step, initial)
        for label, limit in zip((TARGET_U, TARGET_V), TARGET_LIMITS_MM, strict=True):
            meshcat.AddSlider(label, -limit, limit, TARGET_STEP_MM, 0)
        for label in (BAND_BELOW, BAND_ABOVE):
            meshcat.AddSlider(label, 0, MAX_OFFSET_EV, 0.1, BAND_DEFAULT)
        meshcat.AddButton(COMPARE)
        meshcat.SetProperty(root, "planning_frame", [float(PlanningStatus.IDLE)])
        if point_source_m is not None:
            meshcat.SetObject(f"{root}/IP", Sphere(0.002), Rgba(1, 1, 1))
            meshcat.SetTransform(f"{root}/IP", RigidTransform(point_source_m))
        self.alignment = AlignmentPreview(meshcat, spectrometer, rig, root)
        self.last = None
        self.last_target = None
        self.planner_clicks = 0
        self.planner_key: tuple[object, ...] | None = None
        self.planner_band: tuple[float, float] | None = None

    def close(self) -> None:
        self.alignment.close()

    def update_planner(
        self, context: PoseT, energy: float, width: float, pose_key: tuple[float, ...],
    ) -> None:
        controls = self.meshcat
        clicks = controls.GetButtonClicks(COMPARE)
        below, above = (controls.GetSliderValue(label) for label in (BAND_BELOW, BAND_ABOVE))
        if self.planner_band != (below, above):
            controls.SetProperty(self.root, "planning_band", [below, above])
            self.planner_band = (below, above)
        key = (energy, width, pose_key, below, above)
        if clicks == self.planner_clicks:
            if self.planner_key is not None and self.planner_key != key:
                self.planner_key = None
                controls.SetProperty(self.root, "planning_frame", [float(PlanningStatus.STALE)])
            return
        self.planner_clicks = clicks
        self.planner_key = None
        try:
            energies, comparisons = compare_reflections(
                self.spectrometer, context, energy, below, above, width,
            )
        except (ValueError, RuntimeError):
            logging.getLogger(__name__).exception("Simulated reflection comparison failed")
            controls.SetProperty(self.root, "planning_frame", [float(PlanningStatus.FAILED)])
            return
        self.planner_key = key
        data = [float(PlanningStatus.READY), energy, width, below, above, len(energies), *energies]
        for comparison in comparisons:
            data.extend((comparison.reflection, comparison.bragg_deg))
            for sample in comparison.points:
                for point in sample:
                    data.extend((point.capture, point.u_mm, point.v_mm, point.edge_mm))
        controls.SetProperty(self.root, "planning_frame", [float(value) for value in data])

    def update(self, context: PoseT, positions: dict[str, float]) -> None:
        controls = self.meshcat
        line = int(controls.GetSliderValue(LINE))
        reflection = int(controls.GetSliderValue(REFLECTION))
        energy = self.lines[line][1] if line < len(self.lines) else controls.GetSliderValue(ENERGY)
        if reflection < len(self.reflections):
            spacing, order = self.reflections[reflection].spacing_a, 1
        else:
            spacing = controls.GetSliderValue(SPACING)
            order = int(controls.GetSliderValue(ORDER))
        width = controls.GetSliderValue(WIDTH)
        target = (controls.GetSliderValue(TARGET_U), controls.GetSliderValue(TARGET_V))
        if target != self.last_target:
            controls.SetProperty(self.root, "alignment_target", list(target))
            self.last_target = target
        pose_key = tuple(positions[axis.key] for axis in self.axes)
        self.update_planner(context, energy, width, pose_key)
        key = (line, reflection, energy, spacing, order, width, pose_key)
        request = AlignmentRequest(energy, spacing, order, width, target)
        self.alignment.update(context, positions, key, request=request)
        if key == self.last:
            return
        self.last = key
        theta, detector, traces = self.spectrometer.trace(context, energy, spacing, order, width)
        for index, (trace, color) in enumerate(zip(traces, self.colors, strict=True), start=1):
            path = f"{self.root}/crystal-{index}"
            if not len(trace.bounce_m) or trace.preview_start_m is None:
                controls.Delete(path)
                continue
            start = np.vstack((trace.preview_start_m, trace.bounce_m))
            end = np.vstack((trace.bounce_m, trace.preview_end_m))
            controls.SetLineSegments(path, start.T, end.T, rgba=Rgba(*color, 0.8))
            controls.SetProperty(f"{path}/<object>", "material.depthTest", False)
        u, v = detector.u * ACTIVE_SIZE_M[0] / 2, detector.v * ACTIVE_SIZE_M[1] / 2
        corners = np.array([-u - v, u - v, u + v, -u + v]) + detector.center_m
        border = f"{self.root}/ePix100"
        controls.SetLineSegments(border, corners.T, np.roll(corners, -1, axis=0).T,
                                 rgba=Rgba(0.75, 0.85, 1, 1))
        controls.SetProperty(f"{border}/<object>", "material.depthTest", False)

        image, centroid, rms = detector_image(traces)
        data = [
            line, reflection, energy, spacing, order, width,
            -1 if theta is None else math.degrees(theta),
            *(centroid.tolist() if centroid is not None else (0, 0)),
            *(rms.tolist() if rms is not None else (0, 0)),
        ]
        for trace in traces:
            data.extend((trace.accepted, len(trace.weights), *(trace.incidence_deg or (-1, -1))))
        data.extend(image_bins(image))
        controls.SetProperty(self.root, "detector_frame", [float(value) for value in data])
