"""Bounded alignment search for a shared simulated ePix100 spot from four crystals."""

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from threading import Event

import numpy as np
from controls import AssemblySliderJoint, with_followers
from pydrake.systems.framework import Context
from spectroscopy import (
    ACTIVE_SIZE_M,
    CRYSTAL_INDICES,
    MODEL,
    REFLECTIONS,
    Array,
    CrystalTrace,
    Spectrometer,
    bragg_angle,
    detector_image,
)

from twin_lab.scene import DrakeScene

PREFIX = f"{MODEL}::"
STAGE_STEP = 0.05
DETECTOR_X = "epix100_x_joint"
MIN_SIGNAL_HITS = 32
STARTING_POSE_LIMIT = 4
SHORTLIST_BRAGG_DEG = 79.0  # Near the demonstrated 250 mm Fe and Co setups.
COMMON_AXES = (
    "parker_lift_joint", "parker_cross_joint", "analyzer_rotation_joint",
    DETECTOR_X, "epix100_y_joint", "epix100_z_joint", "epix100_tilt_joint",
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

    def signal_rank(self) -> tuple[int, int]:
        return signal_rank(self.hits, self.accepted)


def signal_rank(hits: tuple[int, ...], accepted: tuple[int, ...]) -> tuple[int, int]:
    usable = sum(hit >= MIN_SIGNAL_HITS for hit in hits)
    captured = sum(
        hit >= max(MIN_SIGNAL_HITS, 0.8 * rays) for hit, rays in zip(hits, accepted, strict=True)
    )
    return usable, captured


@dataclass(frozen=True)
class AlignmentResult:
    start: tuple[float, ...]
    target: tuple[float, ...]
    detector_target_mm: tuple[float, float]
    before: AlignmentImage
    after: AlignmentImage
    x_limit_mm: float | None = None


@dataclass(frozen=True)
class StartingPose:
    reflection: int
    alignment: AlignmentResult


def starting_reflections(energy_ev: float) -> list[int]:
    """Prefer a matching setup reference, then angles near the 250 mm examples."""
    ranked = []
    for index, preset in enumerate(REFLECTIONS):
        theta = bragg_angle(energy_ev, preset.spacing_a, 1)
        if theta is not None:
            ranked.append((
                not preset.matches_reference(energy_ev),
                abs(math.degrees(theta) - SHORTLIST_BRAGG_DEG),
                index,
            ))
    return [index for _, _, index in sorted(ranked)[:STARTING_POSE_LIMIT]]


def find_starting_poses(
    scene: DrakeScene,
    context: Context,
    spectrometer: Spectrometer,
    joints: Sequence[AssemblySliderJoint],
    followers: Mapping[str, tuple[str, Mapping]],
    positions: Mapping[str, float],
    request: AlignmentRequest,
    cancel: Event,
    *,
    progress: Callable[[tuple[int, int, int]], None] | None = None,
) -> list[StartingPose]:
    """Rank the best bounded single-line poses from the reflection shortlist."""
    poses = []
    eligible = starting_reflections(request.energy_ev)
    for step, index in enumerate(eligible, start=1):
        if cancel.is_set():
            return []
        if progress is not None:
            progress((step, len(eligible), index))
        result = find_alignment(
            scene, context.Clone(), spectrometer, joints, followers, positions,
            replace(request, spacing_a=REFLECTIONS[index].spacing_a, order=1),
            cancel, find_signal=True,
        )
        if result is not None:
            poses.append(StartingPose(index, result))

    def rank(pose: StartingPose) -> tuple[int, int, bool, float, int]:
        after = pose.alignment.after
        assert after.rms_mm is not None
        precedent = REFLECTIONS[pose.reflection].matches_reference(request.energy_ev)
        spread = float(np.linalg.norm(after.rms_mm))
        return *after.signal_rank(), precedent, -spread, sum(after.hits)

    return [] if cancel.is_set() else sorted(poses, key=rank, reverse=True)


def find_alignment(
    scene: DrakeScene,
    context: Context,
    spectrometer: Spectrometer,
    joints: Sequence[AssemblySliderJoint],
    followers: Mapping[str, tuple[str, Mapping]],
    positions: Mapping[str, float],
    request: AlignmentRequest,
    cancel: Event,
    *,
    find_signal: bool = False,
) -> AlignmentResult | None:
    """Preview a better focus (or search for signal) on a private context."""
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
    min_hits = tuple(max(MIN_SIGNAL_HITS, hits) for hits in before.hits)
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
        desired_hits = 700 if find_signal else max(700, before.hits[crystal])
        return cost + 80 * (1 - capture)**2 + 0.001 * max(0, desired_hits - hits)**2

    def valid(traces: list[CrystalTrace]) -> bool:
        return all(
            len(ray.weights) >= max(minimum, 0.8 * ray.accepted)
            for ray, minimum in zip(traces, min_hits, strict=True)
        )

    best_cost = sum(score(ray, i) for i, ray in enumerate(home_traces))
    best_signal = (0, 0)
    winner: AlignmentResult | None = None
    rng = np.random.default_rng(42)

    def record(traces: list[CrystalTrace], costs: Array) -> None:
        nonlocal best_cost, best_signal, winner
        cost = float(costs.sum())
        if find_signal:
            signal = signal_rank(
                tuple(len(ray.weights) for ray in traces), tuple(ray.accepted for ray in traces),
            )
            improved = signal[0] > 0 and (
                signal > best_signal or (signal == best_signal and cost < best_cost - 1e-4)
            )
        else:
            signal = best_signal
            improved = cost < best_cost - 1e-4 and valid(traces)
        if improved:
            best_signal = signal
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

    if find_signal:
        record_current()
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

    if cancel.is_set() or winner is None:
        return None
    centroid, rms = winner.after.centroid_mm, winner.after.rms_mm
    assert centroid is not None and rms is not None  # The winning pose has detector hits.
    x_axis = AXES.index(DETECTOR_X)
    ticks = np.rint(np.asarray(winner.target) / STAGE_STEP)
    # Positive x moves the sensor opposite +u, increasing each hit's local u by the same amount.
    # Center the displayed weighted centroid after focusing, without clipping any more signal.
    error_u = target[0] - centroid[0]
    correction = int(np.clip(
        np.rint(error_u / STAGE_STEP), first[x_axis] - ticks[x_axis], last[x_axis] - ticks[x_axis],
    ))
    while correction and not cancel.is_set():
        candidate = ticks.copy()
        candidate[x_axis] += correction
        set_pose(candidate)
        after = AlignmentImage.from_traces(trace())
        if (
            after.centroid_mm is not None and after.rms_mm is not None
            and all(a >= b for a, b in zip(after.hits, winner.after.hits, strict=True))
            and abs(target[0] - after.centroid_mm[0]) < abs(error_u)
            and abs(target[1] - after.centroid_mm[1]) <= abs(target[1] - centroid[1]) + 1e-7
            and np.all(after.rms_mm <= rms + 1e-7)
        ):
            ticks = candidate
            error_u = target[0] - after.centroid_mm[0]
            winner = replace(
                winner, target=tuple(np.round(ticks * STAGE_STEP, 2).tolist()), after=after,
            )
            break
        correction = math.trunc(correction / 2)
    if cancel.is_set():
        return None
    if (
        (error_u < -STAGE_STEP / 2 and ticks[x_axis] == first[x_axis])
        or (error_u > STAGE_STEP / 2 and ticks[x_axis] == last[x_axis])
    ):
        winner = replace(winner, x_limit_mm=winner.target[x_axis])
    return winner
