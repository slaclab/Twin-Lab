"""Bounded alignment search for a shared simulated ePix100 spot."""

import math
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from threading import Event

import numpy as np

from .spectroscopy import (
    ACTIVE_SIZE_M,
    Array,
    CrystalTrace,
    ReflectionPreset,
    Spectrometer,
    bragg_angle,
    detector_image,
)

STAGE_STEP = 0.05
MIN_SIGNAL_HITS = 32
STARTING_POSE_LIMIT = 4
QUICK_TARGET_ERROR_MM = 2.0


@dataclass(frozen=True)
class AlignmentAxis:
    key: str
    label: str
    lower: float
    upper: float
    to_slider: Callable[[float], float]
    from_slider: Callable[[float], float]


@dataclass(frozen=True)
class AlignmentRig[PoseT]:
    shared: tuple[AlignmentAxis, ...]
    independent: tuple[tuple[AlignmentAxis, ...], ...]
    set_positions: Callable[[PoseT, Mapping[str, float]], None]
    clone: Callable[[PoseT], PoseT]
    detector_x: str | None = None

    @property
    def axes(self) -> tuple[AlignmentAxis, ...]:
        return (*self.shared, *(axis for group in self.independent for axis in group))

    def endpoint(
        self, positions: Mapping[str, float], target: tuple[float, ...],
    ) -> dict[str, float]:
        return {
            **positions,
            **{
                axis.key: axis.from_slider(value)
                for axis, value in zip(self.axes, target, strict=True)
            },
        }


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


@dataclass(frozen=True)
class ClearanceSearch:
    allows: Callable[[Mapping[str, float], Event], bool]
    home: Mapping[str, float]
    lock_groups: tuple[frozenset[str], ...]


def starting_reflections(
    energy_ev: float, reflections: tuple[ReflectionPreset, ...], shortlist_angle_deg: float,
    *, exclude_spacing_a: float | None = None,
) -> list[int]:
    """Prefer a matching setup reference, then angles near the model's nominal angle."""
    ranked = []
    for index, preset in enumerate(reflections):
        if preset.spacing_a == exclude_spacing_a:
            continue
        theta = bragg_angle(energy_ev, preset.spacing_a, 1)
        if theta is not None:
            ranked.append((
                not preset.matches_reference(energy_ev),
                abs(math.degrees(theta) - shortlist_angle_deg),
                index,
            ))
    return [index for _, _, index in sorted(ranked)[:STARTING_POSE_LIMIT]]


def find_starting_poses[PoseT](
    context: PoseT,
    spectrometer: Spectrometer[PoseT],
    rig: AlignmentRig[PoseT],
    positions: Mapping[str, float],
    request: AlignmentRequest,
    cancel: Event,
    *,
    progress: Callable[[tuple[int, int, int]], None] | None = None,
    clearance: ClearanceSearch | None = None,
    alternatives_only: bool = False,
) -> list[StartingPose]:
    """Rank the best bounded single-line poses from the reflection shortlist."""
    poses = []
    reflections = spectrometer.reflections
    eligible = starting_reflections(
        request.energy_ev, reflections, spectrometer.shortlist_angle_deg,
        exclude_spacing_a=request.spacing_a if alternatives_only and request.order == 1 else None,
    )
    for step, index in enumerate(eligible, start=1):
        if cancel.is_set():
            return []
        if progress is not None:
            progress((step, len(eligible), index))
        result = find_alignment(
            rig.clone(context), spectrometer, rig, positions,
            replace(request, spacing_a=reflections[index].spacing_a, order=1),
            cancel, find_signal=True, clearance=clearance,
        )
        if result is not None:
            poses.append(StartingPose(index, result))

    def rank(pose: StartingPose) -> tuple[int, int, bool, float, int]:
        after = pose.alignment.after
        assert after.rms_mm is not None
        precedent = reflections[pose.reflection].matches_reference(request.energy_ev)
        spread = float(np.linalg.norm(after.rms_mm))
        return *after.signal_rank(), precedent, -spread, sum(after.hits)

    return [] if cancel.is_set() else sorted(poses, key=rank, reverse=True)


def find_alignment[PoseT](
    context: PoseT,
    spectrometer: Spectrometer[PoseT],
    rig: AlignmentRig[PoseT],
    positions: Mapping[str, float],
    request: AlignmentRequest,
    cancel: Event,
    *,
    find_signal: bool = False,
    clearance: ClearanceSearch | None = None,
    quick: bool = False,
    on_interference: Callable[[], None] | None = None,
) -> AlignmentResult | None:
    """Rank optical solutions from bounded searches, discarding interfering endpoints."""
    if clearance is None:
        return _find_alignment(
            context, spectrometer, rig, positions, request, cancel, find_signal=find_signal,
        )

    def bound(axis: AlignmentAxis, settings: Mapping[str, float]) -> AlignmentAxis:
        if axis.key not in settings:
            return axis
        value = settings[axis.key]
        return replace(axis, lower=value, upper=value)

    def alternate_rigs() -> Iterator[AlignmentRig[PoseT]]:
        if not quick:
            yield rig
        seen = set()
        groups = reversed(clearance.lock_groups) if quick else iter(clearance.lock_groups)
        for locked in groups:
            for anchor in (positions, clearance.home):
                settings = {}
                for axis in rig.axes:
                    if axis.key in locked:
                        low = math.ceil(axis.lower / STAGE_STEP - 1e-10)
                        high = math.floor(axis.upper / STAGE_STEP + 1e-10)
                        tick = round(axis.to_slider(anchor[axis.key]) / STAGE_STEP)
                        settings[axis.key] = min(max(tick, low), high) * STAGE_STEP
                key = tuple(settings.items())
                if key in seen:
                    continue
                seen.add(key)

                yield replace(
                    rig, shared=tuple(bound(axis, settings) for axis in rig.shared),
                    independent=tuple(
                        tuple(bound(axis, settings) for axis in group) for group in rig.independent
                    ),
                )
        if quick:
            yield rig

    def rank(result: AlignmentResult) -> tuple[int, int, float, float, int]:
        after = result.after
        assert after.centroid_mm is not None and after.rms_mm is not None
        error = float(np.linalg.norm(after.centroid_mm - request.target_mm))
        return *after.signal_rank(), -error, -float(np.linalg.norm(after.rms_mm)), sum(after.hits)

    best = None
    checked = set()
    for candidate_rig in alternate_rigs():
        if cancel.is_set():
            return None
        result = _find_alignment(
            rig.clone(context), spectrometer, candidate_rig, positions, request, cancel,
            find_signal=find_signal,
        )
        if result is None or result.target in checked:
            continue
        if best is not None and rank(result) <= rank(best):
            continue
        checked.add(result.target)
        if clearance.allows(rig.endpoint(positions, result.target), cancel):
            best = result
            if quick:
                _, captured, neg_error, _, _ = rank(best)
                if (
                    captured == len(spectrometer.crystal_labels)
                    and -neg_error <= QUICK_TARGET_ERROR_MM
                ):
                    break
        elif on_interference is not None and not cancel.is_set():
            on_interference()
    return None if cancel.is_set() else best


def _find_alignment[PoseT](
    context: PoseT,
    spectrometer: Spectrometer[PoseT],
    rig: AlignmentRig[PoseT],
    positions: Mapping[str, float],
    request: AlignmentRequest,
    cancel: Event,
    *,
    find_signal: bool,
) -> AlignmentResult | None:
    """Preview a better focus (or search for signal) on a private context."""
    target = np.asarray(request.target_mm)
    if not np.all(np.isfinite(target) & (np.abs(target) < ACTIVE_SIZE_M * 500)):
        raise ValueError("The alignment target must be inside the active ePix100 rectangle")
    theta = bragg_angle(request.energy_ev, request.spacing_a, request.order)
    if theta is None or cancel.is_set():
        return None

    controls = rig.axes
    crystal_indices = tuple(range(len(spectrometer.crystal_labels)))
    start = np.array([axis.to_slider(positions[axis.key]) for axis in controls])
    bounds = np.array([(axis.lower, axis.upper) for axis in controls])
    first = np.ceil(bounds[:, 0] / STAGE_STEP - 1e-10)
    last = np.floor(bounds[:, 1] / STAGE_STEP + 1e-10)
    if np.any(last < first):
        raise ValueError("No slider positions in the spectroscopy limits")
    current = np.clip(np.round(start / STAGE_STEP), first, last)
    applied = start / STAGE_STEP
    shared = np.arange(len(rig.shared))
    axis_indices = {axis.key: i for i, axis in enumerate(controls)}
    blocks = [
        np.array([axis_indices[axis.key] for axis in group]) for group in rig.independent
    ]

    def trace(crystals: Sequence[int] = crystal_indices) -> list[CrystalTrace]:
        return spectrometer.trace(
            context, request.energy_ev, request.spacing_a, request.order,
            request.half_width_deg, crystals=crystals, aim=True,
        )[2]

    def set_pose(ticks: Array) -> None:
        nonlocal applied
        values = {}
        for i in np.flatnonzero(ticks != applied):
            axis = controls[i]
            values[axis.key] = axis.from_slider(round(float(ticks[i]) * STAGE_STEP, 2))
        rig.set_positions(context, values)
        applied = ticks

    home_traces = trace()
    before = AlignmentImage.from_traces(home_traces)
    min_hits = tuple(max(MIN_SIGNAL_HITS, hits) for hits in before.hits)
    theta_deg = math.degrees(theta)

    def enough_signal(ray: CrystalTrace, crystal: int) -> bool:
        return len(ray.weights) >= max(min_hits[crystal], 0.8 * ray.accepted)

    refine_flat = not find_signal and all(
        ray.aim_cost is not None and enough_signal(ray, i)
        for i, ray in enumerate(home_traces)
    )

    def score(ray: CrystalTrace, crystal: int) -> float:
        if ray.aim_cost is not None:
            if refine_flat and enough_signal(ray, crystal):
                # Once captured, aim the measured footprint rather than the central ray,
                # which can be displaced from the spot by clipping at the crystal seat.
                centroid = np.average(ray.uv_m, axis=0, weights=ray.weights) * 1000
                return float(np.sum((centroid - target) ** 2))
            uv = ray.projected_uv_m
            target_cost = 0.0 if uv is None or not len(uv) else float(
                np.mean(np.sum((uv * 1000 - target) ** 2, axis=1))
            )
            return ray.aim_cost + target_cost + (1e6 if refine_flat else 0)
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
        return all(enough_signal(ray, i) for i, ray in enumerate(traces))

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
            if crystals == crystal_indices:
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
    # move multiple spots and therefore need the joint objective.
    for i, block in enumerate(blocks):
        for scale, count in ((1.0, 144), (0.12, 80), (0.04, 64), (0.012, 64)):
            if cancel.is_set():
                return None
            search(block, (i,), scale, count)
    record_current()
    for scale in (0.15, 0.06, 0.025, 0.01, 0.004, 0.0015):
        if cancel.is_set():
            return None
        search(shared, crystal_indices, scale, 80)
        for i, block in enumerate(blocks):
            search(block, (i,), scale, 50)
        record_current()

    if cancel.is_set() or winner is None:
        return None
    if rig.detector_x is None:
        return winner
    centroid, rms = winner.after.centroid_mm, winner.after.rms_mm
    assert centroid is not None and rms is not None  # The winning pose has detector hits.
    x_axis = axis_indices[rig.detector_x]
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
