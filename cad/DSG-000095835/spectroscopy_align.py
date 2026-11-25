"""Bounded alignment search for a shared simulated ePix100 spot from four crystals."""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from threading import Event

import numpy as np
from controls import AssemblySliderJoint, with_followers
from pydrake.systems.framework import Context
from spectroscopy import (
    ACTIVE_SIZE_M,
    CRYSTAL_INDICES,
    MODEL,
    Array,
    CrystalTrace,
    Spectrometer,
    bragg_angle,
    detector_image,
)

from twin_lab.scene import DrakeScene

PREFIX = f"{MODEL}::"
STAGE_STEP = 0.05
COMMON_AXES = (
    "parker_lift_joint", "parker_cross_joint", "analyzer_rotation_joint",
    "epix100_x_joint", "epix100_y_joint", "epix100_z_joint", "epix100_tilt_joint",
)
CRYSTAL_AXES = tuple(
    tuple(f"crystal_{index + 1}_{axis}_joint" for axis in ("translation", "rotation", "tilt"))
    for index in CRYSTAL_INDICES
)
AXES = (
    *COMMON_AXES,
    *(name for axes in CRYSTAL_AXES for name in axes),
)


@dataclass(frozen=True)
class AlignmentRequest:
    energy_ev: float
    spacing_a: float
    order: int
    half_width_deg: float
    target_mm: tuple[float, float] = (0.0, 0.0)


@dataclass(frozen=True)
class AlignmentImage:
    image: Array
    centroid_mm: Array | None
    rms_mm: Array | None
    hits: tuple[int, ...]
    accepted: tuple[int, ...]

    @classmethod
    def from_traces(cls, traces: list[CrystalTrace]) -> "AlignmentImage":
        image, centroid, rms = detector_image(traces)
        return cls(
            image, centroid, rms, tuple(len(trace.weights) for trace in traces),
            tuple(trace.accepted for trace in traces),
        )


@dataclass(frozen=True)
class AlignmentResult:
    start: tuple[float, ...]
    target: tuple[float, ...]
    detector_target_mm: tuple[float, float]
    before: AlignmentImage
    after: AlignmentImage


def find_alignment(
    scene: DrakeScene,
    context: Context,
    spectrometer: Spectrometer,
    joints: Sequence[AssemblySliderJoint],
    followers: Mapping[str, tuple[str, Mapping]],
    positions: Mapping[str, float],
    request: AlignmentRequest,
    cancel: Event,
) -> AlignmentResult | None:
    """Find a better pose on a private context already at the captured slider positions."""
    target = np.asarray(request.target_mm)
    if not np.all(np.isfinite(target) & (np.abs(target) < ACTIVE_SIZE_M * 500)):
        raise ValueError("The alignment target must be inside the active ePix100 rectangle")
    theta = bragg_angle(request.energy_ev, request.spacing_a, request.order)
    if theta is None or cancel.is_set():
        return None

    by_name = {joint.joint_name: joint for joint in joints}
    controls = [by_name[name] for name in AXES]
    start = np.array([
        (positions[PREFIX + joint.joint_name] + joint.logical_offset) * joint.scale
        for joint in controls
    ])
    bounds = np.array([joint.spectroscopy_bounds()[:2] for joint in controls])
    first = np.ceil(bounds[:, 0] / STAGE_STEP)
    last = np.floor(bounds[:, 1] / STAGE_STEP)
    if np.any(last < first):
        raise ValueError("No slider positions in the spectroscopy limits")
    current = np.clip(np.round(start / STAGE_STEP), first, last)
    applied = start / STAGE_STEP
    shared = np.arange(len(COMMON_AXES))
    blocks = [
        np.array([AXES.index(name) for name in names])
        for names in CRYSTAL_AXES
    ]

    def trace(crystals: Sequence[int] = CRYSTAL_INDICES) -> list[CrystalTrace]:
        return spectrometer.trace(
            context, request.energy_ev, request.spacing_a, request.order,
            request.half_width_deg, crystals=crystals, aim=True,
        )[2]

    def set_pose(ticks: Array) -> None:
        nonlocal applied
        values = {}
        for i in np.flatnonzero(ticks != applied):
            joint = controls[i]
            value = joint.to_sdf(round(float(ticks[i]) * STAGE_STEP, 2))
            values[PREFIX + joint.joint_name] = min(max(value, joint.sdf_lower), joint.sdf_upper)
        scene.set_joint_positions(context, with_followers(values, followers, prefix=PREFIX))
        applied = ticks

    home_traces = trace()
    before = AlignmentImage.from_traces(home_traces)
    min_hits = tuple(max(32, hits) for hits in before.hits)
    theta_deg = math.degrees(theta)

    def score(ray: CrystalTrace, crystal: int) -> float:
        # Use the infinite detector plane to guide rays back from outside the active rectangle.
        uv = ray.projected_uv_m
        if uv is None or not len(uv):
            low, high = ray.incidence_deg or (0, 0)
            gap = max(0, low - theta_deg, theta_deg - high)
            return 20_000 + 100 * gap**2
        error = uv * 1000 - target
        cost = float(np.mean(np.sum(error**2, axis=1)))
        hits = len(ray.weights)
        # Trade spot size against throughput, not the number of rays that happened to clip.
        capture = hits / ray.accepted
        return (cost + 80 * (1 - capture)**2
                + 0.001 * max(0, max(700, before.hits[crystal]) - hits)**2)

    def valid(traces: list[CrystalTrace]) -> bool:
        return all(
            len(ray.weights) >= max(minimum, 0.8 * ray.accepted)
            for ray, minimum in zip(traces, min_hits, strict=True)
        )

    best_cost = sum(score(ray, i) for i, ray in enumerate(home_traces))
    winner: AlignmentResult | None = None
    rng = np.random.default_rng(42)

    def record(traces: list[CrystalTrace], costs: Array) -> None:
        nonlocal best_cost, winner
        cost = float(costs.sum())
        if cost < best_cost - 1e-4 and valid(traces):
            best_cost = cost
            winner = AlignmentResult(
                tuple(start.tolist()), tuple(np.round(current * STAGE_STEP, 2).tolist()),
                request.target_mm, before, AlignmentImage.from_traces(traces),
            )

    def search(indices: Array, crystals: tuple[int, ...], scale: float, count: int) -> None:
        nonlocal current
        set_pose(current)
        traces = trace(crystals)
        best = sum(score(ray, i) for i, ray in zip(crystals, traces, strict=True))
        low, high = first[indices], last[indices]
        for sample in range(count):
            if cancel.is_set():
                return
            candidate = current.copy()
            if scale == 1:
                values = rng.uniform(low, high)
            else:
                step = rng.normal(size=len(indices)) * (high - low) * scale
                if sample % 2:
                    step[np.arange(len(indices)) != (sample // 2) % len(indices)] = 0
                values = candidate[indices] + step
            candidate[indices] = np.clip(np.round(values), low, high)
            if not np.any(candidate != current):
                continue
            set_pose(candidate)
            traces = trace(crystals)
            costs = np.array([score(ray, i) for i, ray in zip(crystals, traces, strict=True)])
            old = current
            current = candidate
            if crystals == CRYSTAL_INDICES:
                record(traces, costs)
            if (cost := float(costs.sum())) < best:
                best = cost
            else:
                current = old

    def record_current() -> None:
        set_pose(current)
        traces = trace()
        record(traces, np.array([score(ray, i) for i, ray in enumerate(traces)]))

    # Independent crystal stages are cheap to explore one at a time; the common stages
    # move multiple spots and therefore need the joint four-crystal objective.
    for i, block in enumerate(blocks):
        for scale, count in ((1.0, 144), (0.12, 80), (0.04, 64), (0.012, 64)):
            if cancel.is_set():
                return None
            search(block, (i,), scale, count)
    record_current()
    for scale in (0.15, 0.06, 0.025, 0.01, 0.004, 0.0015):
        if cancel.is_set():
            return None
        search(shared, CRYSTAL_INDICES, scale, 80)
        for i, block in enumerate(blocks):
            search(block, (i,), scale, 50)
        record_current()
    return winner
