"""Publish the 95835 spectroscopy preview through the existing Meshcat connection."""

import json
import logging
import math
from collections.abc import Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from enum import IntEnum
from pathlib import Path
from threading import Event

import numpy as np
from controls import AssemblySliderJoint
from pydrake.geometry import Meshcat, Rgba, Sphere
from pydrake.math import RigidTransform
from spectroscopy import (
    ACTIVE_SIZE_M,
    COLS,
    IP_M,
    LINES,
    REFLECTIONS,
    ROWS,
    Array,
    Spectrometer,
    bragg_angle,
    detector_image,
)
from spectroscopy_align import AXES, AlignmentRequest, AlignmentResult, find_alignment

ROOT = "/95835-spectroscopy"
LINE = "Emission preset"
REFLECTION = "Crystal preset (all four)"
ENERGY = "Custom emission energy (eV)"
SPACING = "Custom d-spacing (angstrom)"
ORDER = "Custom Bragg order"
WIDTH = "Bragg half-width (degrees)"
COLORS = ((0.15, 0.82, 0.96), (0.28, 0.91, 0.38), (0.95, 0.50, 0.87), (0.99, 0.62, 0.25))
ALIGN = "Preview simulated alignment"
APPLY = "Apply proposed simulator pose"
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
    PAUSE_ANIMATION = 6
    FAILED = 7


def detector_panel(joints: Sequence[AssemblySliderJoint]) -> str:
    labels = {joint.joint_name: joint.label for joint in joints}
    options = {
        "root": ROOT,
        "lineLabel": LINE,
        "reflectionLabel": REFLECTION,
        "energyLabel": ENERGY,
        "spacingLabel": SPACING,
        "orderLabel": ORDER,
        "lines": [*(f"{label} · {energy:.1f} eV" for label, energy in LINES), "Custom energy"],
        "reflections": [*(label for label, _ in REFLECTIONS), "Custom d-spacing / order"],
        "sizeMm": (ACTIVE_SIZE_M * 1000).tolist(),
        "cols": COLS,
        "rows": ROWS,
        "colors": [[round(255 * c) for c in color] for color in COLORS],
        "alignment": {
            "previewLabel": ALIGN,
            "applyLabel": APPLY,
            "targetLabels": [TARGET_U, TARGET_V],
            "targetLimitsMm": TARGET_LIMITS_MM,
            "targetStepMm": TARGET_STEP_MM,
            "axes": [labels[name] for name in AXES],
            "status": {status.name: status.value for status in AlignmentStatus},
        },
    }
    return Path(__file__).with_name("spectroscopy_panel.html").read_text(
        encoding="utf-8"
    ).replace("__OPTIONS__", json.dumps(options))


def image_bins(image: Array) -> list[float]:
    flat = image.ravel()
    nonzero = np.flatnonzero(flat)
    if not len(nonzero):
        return []
    return np.column_stack((nonzero, flat[nonzero] / flat[nonzero].max())).ravel().tolist()


class AlignmentPreview:
    def __init__(self, meshcat: Meshcat, scene, spectrometer, joints, followers):
        self.meshcat = meshcat
        self.scene = scene
        self.spectrometer = spectrometer
        self.joints = joints
        self.followers = followers
        self.by_name = {joint.joint_name: joint for joint in joints}
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="spectroscopy-align")
        self.cancel = Event()
        self.future: Future[AlignmentResult | None] | None = None
        self.proposal: AlignmentResult | None = None
        self.snapshot: tuple[object, ...] | None = None
        self.clicks = (0, 0)
        meshcat.AddButton(ALIGN)
        meshcat.AddButton(APPLY)
        self.publish(AlignmentStatus.IDLE)

    def publish(self, status: AlignmentStatus) -> None:
        data = [float(status)]
        if status == AlignmentStatus.READY and self.proposal is not None:
            proposal = self.proposal
            data.extend(proposal.detector_target_mm)
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
        self.meshcat.SetProperty(ROOT, "alignment_frame", data)

    def update(
        self, context, positions, key, *, request: AlignmentRequest, automatic: bool,
    ) -> None:
        clicks = self.meshcat.GetButtonClicks(ALIGN), self.meshcat.GetButtonClicks(APPLY)
        requested, apply = (new > old for new, old in zip(clicks, self.clicks, strict=True))
        self.clicks = clicks
        key = (*key, request.target_mm, automatic)

        if self.snapshot is not None and key != self.snapshot:
            self.cancel.set()
            self.proposal = None
            self.snapshot = None
            if self.future is None:
                self.publish(AlignmentStatus.STALE)
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
                elif result is None:
                    self.publish(AlignmentStatus.NO_IMPROVEMENT)
                else:
                    self.proposal = result
                    self.publish(AlignmentStatus.READY)
        if requested and self.future is None:
            if bragg_angle(request.energy_ev, request.spacing_a, request.order) is None:
                return
            self.proposal = None
            self.snapshot = None
            if automatic:
                self.publish(AlignmentStatus.PAUSE_ANIMATION)
                return
            self.cancel.clear()
            self.snapshot = key
            self.future = self.executor.submit(
                find_alignment, self.scene, context.Clone(), self.spectrometer, self.joints,
                self.followers, dict(positions), request, self.cancel,
            )
            self.publish(AlignmentStatus.RUNNING)
        elif apply and self.snapshot == key and self.proposal is not None:
            for name, value in zip(AXES, self.proposal.target, strict=True):
                self.meshcat.SetSliderValue(self.by_name[name].label, value)
            self.proposal = None
            self.snapshot = None
            self.publish(AlignmentStatus.APPLIED)

    def close(self) -> None:
        self.cancel.set()
        self.executor.shutdown(wait=True, cancel_futures=True)


class SpectroscopyPreview:
    def __init__(self, meshcat: Meshcat, spectrometer: Spectrometer, scene, joints, followers):
        self.meshcat = meshcat
        self.spectrometer = spectrometer
        for label, low, high, step, initial in (
            (LINE, 0, len(LINES), 1, 0),
            (REFLECTION, 0, len(REFLECTIONS), 1, 0),
            (ENERGY, 1000, 25000, 0.1, LINES[0][1]),
            (SPACING, 0.3, 5, 0.0001, REFLECTIONS[0][1]),
            (ORDER, 1, 8, 1, 1),
            (WIDTH, 0.025, 1, 0.005, 0.05),
        ):
            meshcat.AddSlider(label, low, high, step, initial)
        for label, limit in zip((TARGET_U, TARGET_V), TARGET_LIMITS_MM, strict=True):
            meshcat.AddSlider(label, -limit, limit, TARGET_STEP_MM, 0)
        meshcat.SetObject(f"{ROOT}/IP", Sphere(0.002), Rgba(1, 1, 1))
        meshcat.SetTransform(f"{ROOT}/IP", RigidTransform(IP_M))
        self.alignment = AlignmentPreview(meshcat, scene, spectrometer, joints, followers)
        self.last = None
        self.last_target = None

    def close(self) -> None:
        self.alignment.close()

    def update(self, context, positions: dict[str, float], *, automatic: bool) -> None:
        controls = self.meshcat
        line = int(controls.GetSliderValue(LINE))
        reflection = int(controls.GetSliderValue(REFLECTION))
        energy = LINES[line][1] if line < len(LINES) else controls.GetSliderValue(ENERGY)
        if reflection < len(REFLECTIONS):
            spacing, order = REFLECTIONS[reflection][1], 1
        else:
            spacing = controls.GetSliderValue(SPACING)
            order = int(controls.GetSliderValue(ORDER))
        width = controls.GetSliderValue(WIDTH)
        target = (controls.GetSliderValue(TARGET_U), controls.GetSliderValue(TARGET_V))
        if target != self.last_target:
            controls.SetProperty(ROOT, "alignment_target", list(target))
            self.last_target = target
        # A fixed IP and detector/analyzer poses are the only geometry in this trace.
        pose_key = tuple(
            value for name, value in positions.items()
            if name.split("::")[-1].startswith(("crystal_", "parker_", "analyzer_", "epix100_"))
        )
        key = (line, reflection, energy, spacing, order, width, pose_key)
        request = AlignmentRequest(energy, spacing, order, width, target)
        self.alignment.update(
            context, positions, key, request=request, automatic=automatic,
        )
        if key == self.last:
            return
        self.last = key
        theta, detector, traces = self.spectrometer.trace(context, energy, spacing, order, width)
        for index, (trace, color) in enumerate(zip(traces, COLORS, strict=True), start=1):
            path = f"{ROOT}/crystal-{index}"
            if not len(trace.bounce_m):
                controls.Delete(path)
                continue
            start = np.vstack((np.broadcast_to(IP_M, trace.bounce_m.shape), trace.bounce_m))
            end = np.vstack((trace.bounce_m, trace.preview_end_m))
            controls.SetLineSegments(path, start.T, end.T, rgba=Rgba(*color, 0.8))
            controls.SetProperty(f"{path}/<object>", "material.depthTest", False)
        u, v = detector.u * ACTIVE_SIZE_M[0] / 2, detector.v * ACTIVE_SIZE_M[1] / 2
        corners = np.array([-u - v, u - v, u + v, -u + v]) + detector.center_m
        border = f"{ROOT}/ePix100"
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
        controls.SetProperty(ROOT, "detector_frame", [float(value) for value in data])
