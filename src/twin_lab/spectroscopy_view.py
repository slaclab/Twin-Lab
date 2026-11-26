"""Publish a spectroscopy preview through the existing Meshcat connection."""

import json
import logging
import math
import os
import tempfile
from collections.abc import Callable, Mapping
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from contextlib import contextmanager
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from queue import Empty, SimpleQueue
from threading import Event
from typing import TYPE_CHECKING

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
    STAGE_STEP,
    STARTING_POSE_LIMIT,
    AlignmentRequest,
    AlignmentResult,
    AlignmentRig,
    ClearanceSearch,
    StartingPose,
    find_alignment,
    find_starting_poses,
    signal_rank,
)
from .spectroscopy_plan import CAPTURE_GOAL, MAX_OFFSET_EV, compare_reflections

if TYPE_CHECKING:
    from .collision import ClearanceReport

LINE = "Emission preset"
REFLECTION = "Crystal preset"
ENERGY = "Custom emission energy (eV)"
SPACING = "Custom d-spacing (angstrom)"
ORDER = "Custom Bragg order"
WIDTH = "Bragg half-width (degrees)"
COLORS = ((0.15, 0.82, 0.96), (0.28, 0.91, 0.38), (0.95, 0.50, 0.87), (0.99, 0.62, 0.25))
ALIGN = "Find simulated alignment"
TRY_REFLECTIONS = "Include other named reflections in alignment"
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
    IMPOSSIBLE = 11
    NO_CLEAR_POSE = 12
    NO_STARTING_POSE = 13


class PlanningStatus(IntEnum):
    IDLE = 0
    READY = 1
    STALE = 2
    FAILED = 3


class TargetMoveStatus(IntEnum):
    OK = 0
    NO_SIGNAL = 1
    TRAVEL_LIMIT = 2


class InterferenceStatus(IntEnum):
    PENDING = 0
    CLEAR = 1
    INTERFERENCE = 2
    UNAVAILABLE = 3


type CheckPose = Callable[[Mapping[str, float]], "ClearanceReport | None"]


@dataclass
class _PoseCheck:
    positions: dict[str, float] | None = None
    status: InterferenceStatus = InterferenceStatus.PENDING
    in_flight: tuple[dict[str, float], Future["ClearanceReport | None"]] | None = None


class InterferencePreview:
    """Keep live and proposed endpoint checks off the viewer and alignment threads."""

    def __init__(self, meshcat: Meshcat, root: str, check: CheckPose, executor: Executor):
        self.meshcat = meshcat
        self.root = root
        self.live = _PoseCheck()
        self.proposed = _PoseCheck()
        self.executor = executor
        self.check = check

    def update(
        self, positions: Mapping[str, float] | None, *, proposed: bool = False,
    ) -> InterferenceStatus:
        slot = self.proposed if proposed else self.live
        label = "proposed_interference" if proposed else "live_interference"

        def publish(status: InterferenceStatus, detail: str = "") -> None:
            slot.status = status
            # Meshcat custom properties accept numeric vectors, not strings.
            self.meshcat.SetProperty(
                self.root, label, [float(status), *map(float, detail.encode("utf-8"))],
            )

        if positions != slot.positions:
            slot.positions = None if positions is None else dict(positions)
            publish(InterferenceStatus.PENDING)
        if slot.in_flight is not None:
            checked, future = slot.in_flight
            if future.done():
                slot.in_flight = None
                try:
                    report = future.result()
                except (ValueError, RuntimeError):
                    logging.getLogger(__name__).exception("Spectroscopy interference check failed")
                    report = None
                if checked == slot.positions:
                    if report is None:
                        publish(InterferenceStatus.UNAVAILABLE)
                    elif not report.interference:
                        publish(InterferenceStatus.CLEAR)
                    else:
                        offenders = "\n".join(
                            f"{first} ↔ {second}: {item.distance_m * 1000:+.2f} mm"
                            for item in report.offenders()
                            for first, second in (report.described(item),)
                        )
                        publish(
                            InterferenceStatus.INTERFERENCE,
                            f"{len(report.touching_pairs)} part pairs in contact\n{offenders}",
                        )
        if (
            slot.positions is not None and slot.status == InterferenceStatus.PENDING
            and slot.in_flight is None
        ):
            try:
                slot.in_flight = (slot.positions, self.executor.submit(self.check, slot.positions))
            except (OSError, BrokenProcessPool):
                logging.getLogger(__name__).exception("Spectroscopy collision worker unavailable")
                publish(InterferenceStatus.UNAVAILABLE)
        return slot.status

    def close(self) -> None:
        self.executor.shutdown(wait=True, cancel_futures=True)

    def allows(self, positions: Mapping[str, float], cancel: Event) -> bool:
        """Check a search candidate on the same worker as the live readout."""
        if cancel.is_set():
            return False
        try:
            future = self.executor.submit(self.check, positions)
        except OSError as error:
            raise RuntimeError("Could not start the reviewed interference check") from error
        while not cancel.is_set():
            try:
                report = future.result(timeout=0.1)
            except TimeoutError:
                continue
            if report is None:
                raise RuntimeError("The reviewed interference check is unavailable")
            return not report.interference
        future.cancel()
        return False


def detector_panel[PoseT](
    rig: AlignmentRig[PoseT], *, crystal_labels: tuple[str, ...],
    reflections: tuple[ReflectionPreset, ...], root: str, model_note: str,
    lines: tuple[tuple[str, float], ...] = LINES, focus_goal_mm: float | None = 0.5,
    ray_guides: bool = False, target_moves_detector: bool = False,
    interference: bool = False,
) -> str:
    axes = rig.axes
    options = {
        "root": root,
        "modelNote": model_note,
        "rayGuides": ray_guides,
        "interference": (
            {status.name: status.value for status in InterferenceStatus} if interference else None
        ),
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
            "findLabel": ALIGN,
            "tryReflectionsLabel": TRY_REFLECTIONS,
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
            "targetMovesDetector": target_moves_detector,
            "targetMoveStatus": {status.name: status.value for status in TargetMoveStatus},
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
        root: str, interference: InterferencePreview | None = None,
        clearance: ClearanceSearch | None = None,
    ):
        self.meshcat = meshcat
        self.spectrometer = spectrometer
        self.rig = rig
        self.root = root
        self.interference = interference
        self.clearance = clearance
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="spectroscopy-align")
        self.cancel = Event()
        self.future: Future[AlignmentResult | list[StartingPose] | AlignmentStatus] | None = None
        self.progress: SimpleQueue[tuple[int, ...]] = SimpleQueue()
        self.proposal: AlignmentResult | None = None
        self.starting_poses: list[StartingPose] = []
        self.candidate = 0
        self.snapshot: tuple[object, ...] | None = None
        self.clicks = (0, 0, 0)
        meshcat.AddButton(ALIGN)
        meshcat.AddSlider(TRY_REFLECTIONS, 0, 1, 1, 0)
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

    def check_proposal(self, positions: dict[str, float]) -> bool:
        if self.interference is None:
            return True
        proposed = (
            None if self.proposal is None else self.rig.endpoint(positions, self.proposal.target)
        )
        return self.interference.update(proposed, proposed=True) == InterferenceStatus.CLEAR

    def find_selected(
        self, context: PoseT, positions: dict[str, float], request: AlignmentRequest,
    ) -> AlignmentResult | AlignmentStatus:
        if bragg_angle(request.energy_ev, request.spacing_a, request.order) is None:
            return AlignmentStatus.IMPOSSIBLE
        _, _, traces = self.spectrometer.trace(
            context, request.energy_ev, request.spacing_a, request.order, request.half_width_deg,
        )
        usable, _ = signal_rank(
            tuple(len(ray.weights) for ray in traces), tuple(ray.accepted for ray in traces),
        )
        refine = usable == len(self.spectrometer.crystal_labels) and (
            self.clearance is None or self.clearance.allows(positions, self.cancel)
        )
        rejected = False

        def mark_interference() -> None:
            nonlocal rejected
            rejected = True

        result = find_alignment(
            context, self.spectrometer, self.rig, positions, request, self.cancel,
            find_signal=not refine, clearance=self.clearance, quick=not refine,
            on_interference=mark_interference,
        )
        if result is not None:
            return result
        if refine:
            return AlignmentStatus.NO_IMPROVEMENT
        return AlignmentStatus.NO_CLEAR_POSE if rejected else AlignmentStatus.NO_SIGNAL

    def find(
        self, context: PoseT, positions: dict[str, float], request: AlignmentRequest,
        try_reflections: bool,
    ) -> AlignmentResult | list[StartingPose] | AlignmentStatus:
        reason = AlignmentStatus.IDLE
        if not try_reflections:
            selected = self.find_selected(context, positions, request)
            if (
                not isinstance(selected, AlignmentStatus)
                or selected == AlignmentStatus.NO_IMPROVEMENT
                or self.clearance is None
                or self.cancel.is_set()
            ):
                return selected
            reason = selected
            self.progress.put((reason,))
        poses = find_starting_poses(
            context, self.spectrometer, self.rig, positions, request, self.cancel,
            progress=lambda step: self.progress.put((reason, *step)),
            clearance=self.clearance, alternatives_only=not try_reflections,
        )
        return poses or (AlignmentStatus.NO_STARTING_POSE if try_reflections else reason)

    def update(
        self, context: PoseT, positions: dict[str, float], key: tuple[object, ...], *,
        request: AlignmentRequest,
    ) -> None:
        clicks = tuple(
            self.meshcat.GetButtonClicks(label) for label in (ALIGN, APPLY, CANCEL)
        )
        requested, apply, cancel = (
            new > old for new, old in zip(clicks, self.clicks, strict=True)
        )
        self.clicks = clicks
        key = (*key, request.target_mm)
        if self.interference is not None:
            key = (*key, tuple(sorted(positions.items())))
        show_proposal = False

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
                    self.starting_poses = result
                    self.candidate = 0
                    self.proposal = result[0].alignment
                    self.meshcat.SetSliderValue(CANDIDATE, 0)
                    show_proposal = True
                elif isinstance(result, AlignmentStatus):
                    self.publish(result)
                else:
                    self.proposal = result
                    show_proposal = True
        elif self.future is not None and not self.cancel.is_set():
            try:
                progress = self.progress.get_nowait()
            except Empty:
                pass
            else:
                self.publish(AlignmentStatus.SEARCHING, progress)
        if requested and self.future is None:
            self.proposal = None
            self.starting_poses = []
            self.check_proposal(positions)
            self.cancel.clear()
            self.snapshot = key
            private_context = self.rig.clone(context)
            self.progress = SimpleQueue()
            try_reflections = bool(self.meshcat.GetSliderValue(TRY_REFLECTIONS))
            self.future = self.executor.submit(
                self.find, private_context, dict(positions), request, try_reflections,
            )
            self.publish(AlignmentStatus.SEARCHING if try_reflections else AlignmentStatus.RUNNING)
            return
        if self.starting_poses:
            index = int(self.meshcat.GetSliderValue(CANDIDATE))
            if 0 <= index < len(self.starting_poses) and index != self.candidate:
                self.candidate = index
                self.proposal = self.starting_poses[index].alignment
                show_proposal = True
        clear = self.check_proposal(positions)
        if show_proposal:
            self.publish(AlignmentStatus.READY)
        if apply and clear and self.snapshot == key and self.proposal is not None:
            for axis, value in zip(self.rig.axes, self.proposal.target, strict=True):
                self.meshcat.SetSliderValue(axis.label, value)
            if self.starting_poses:
                self.meshcat.SetSliderValue(
                    REFLECTION, self.starting_poses[self.candidate].reflection,
                )
            self.proposal = None
            self.starting_poses = []
            self.snapshot = None
            self.check_proposal(positions)
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
        detector_target_axes: tuple[tuple[str, int], ...] = (),
        interference: InterferencePreview | None = None,
        clearance: ClearanceSearch | None = None,
    ):
        self.meshcat = meshcat
        self.spectrometer = spectrometer
        self.root = root
        self.axes = rig.axes
        self.interference = interference
        shared = {axis.key: axis for axis in rig.shared}
        self.detector_target_axes = tuple(
            (shared[key], gain) for key, gain in detector_target_axes
        )
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
        self.alignment = AlignmentPreview(meshcat, spectrometer, rig, root, interference, clearance)
        self.last = None
        self.last_target = None
        self.planner_clicks = 0
        self.planner_key: tuple[object, ...] | None = None
        self.planner_band: tuple[float, float] | None = None

    def close(self) -> None:
        self.alignment.close()

    def move_detector_to_target(
        self, context: PoseT, positions: dict[str, float], request: AlignmentRequest,
        previous: tuple[float, float],
    ) -> bool:
        _, _, traces = self.spectrometer.trace(
            context, request.energy_ev, request.spacing_a, request.order, request.half_width_deg,
        )
        _, centroid, _ = detector_image(traces)
        status = TargetMoveStatus.NO_SIGNAL if centroid is None else TargetMoveStatus.OK
        moved = False
        if centroid is not None:
            for i, (axis, gain) in enumerate(self.detector_target_axes):
                target = request.target_mm[i]
                if target == previous[i]:
                    continue
                current = axis.to_slider(positions[axis.key])
                proposed = current + (target - float(centroid[i])) / gain
                bounded = min(max(proposed, axis.lower), axis.upper)
                if bounded != proposed:
                    status = TargetMoveStatus.TRAVEL_LIMIT
                value = round(round(bounded / STAGE_STEP) * STAGE_STEP, 2)
                if abs(value - current) > 1e-9:
                    self.meshcat.SetSliderValue(axis.label, value)
                    moved = True
        self.meshcat.SetProperty(self.root, "target_move_status", float(status))
        return moved

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
        if self.interference is not None:
            self.interference.update(positions)
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
        request = AlignmentRequest(energy, spacing, order, width, target)
        previous = self.last_target
        if target != previous:
            controls.SetProperty(self.root, "alignment_target", list(target))
            self.last_target = target
            if previous is not None and self.detector_target_axes and self.move_detector_to_target(
                context, positions, request, previous,
            ):
                # The viewer will read the new sliders before tracing or aligning again.
                return
        pose_key = tuple(positions[axis.key] for axis in self.axes)
        self.update_planner(context, energy, width, pose_key)
        key = (line, reflection, energy, spacing, order, width, pose_key)
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
            guide = trace.geometric_uv_m
            data.extend((0, 0, 0) if guide is None else (1, *(guide * 1000)))
        data.extend(image_bins(image))
        controls.SetProperty(self.root, "detector_frame", [float(value) for value in data])
