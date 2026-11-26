"""Compare reflection presets across a sampled energy band at one CAD pose."""

import math
from dataclasses import dataclass
from enum import IntEnum

import numpy as np

from .spectroscopy import (
    ACTIVE_SIZE_M,
    CrystalTrace,
    Spectrometer,
    bragg_angle,
)

BAND_SAMPLES = 21
MAX_OFFSET_EV = 200
CAPTURE_GOAL = 0.8


class Coverage(IntEnum):
    NO_BRAGG_ANGLE = -2
    NO_ACCEPTED_SAMPLES = -1


@dataclass(frozen=True)
class BandPoint:
    capture: float
    u_mm: float = 0.0
    v_mm: float = 0.0
    edge_mm: float = 0.0

    @classmethod
    def from_trace(cls, trace: CrystalTrace) -> "BandPoint":
        if not trace.accepted:
            return cls(Coverage.NO_ACCEPTED_SAMPLES)
        if not len(trace.weights):
            return cls(0.0)
        uv_mm = trace.uv_m * 1000
        u, v = np.average(uv_mm, axis=0, weights=trace.weights)
        margin = np.min(ACTIVE_SIZE_M * 500 - np.abs(uv_mm))
        return cls(len(trace.weights) / trace.accepted, float(u), float(v), float(margin))


@dataclass(frozen=True)
class BandComparison:
    reflection: int
    bragg_deg: float
    points: tuple[tuple[BandPoint, ...], ...]

    def geometry_rank(self) -> tuple[int, int, float]:
        """Prefer consistent capture across all crystals, not simulated intensity."""
        complete = sum(all(p.capture >= CAPTURE_GOAL for p in sample) for sample in self.points)
        hits = [p for sample in self.points for p in sample if p.capture > 0]
        return complete, len(hits), min((p.edge_mm for p in hits), default=0.0)


def compare_reflections[PoseT](
    spectrometer: Spectrometer[PoseT],
    context: PoseT,
    energy_ev: float,
    below_ev: float,
    above_ev: float,
    half_width_deg: float,
) -> tuple[tuple[float, ...], list[BandComparison]]:
    """Evaluate evenly spaced energies (including endpoints) without moving stages."""
    if not (
        0 <= below_ev <= MAX_OFFSET_EV and 0 <= above_ev <= MAX_OFFSET_EV
        and math.isfinite(energy_ev) and energy_ev > below_ev
    ):
        raise ValueError("Planning offsets must define a bounded, positive energy interval")
    energies = tuple(np.linspace(
        energy_ev - below_ev, energy_ev + above_ev, BAND_SAMPLES if below_ev + above_ev else 1,
    ).tolist())
    comparisons = []
    for index, preset in enumerate(spectrometer.reflections):
        center = bragg_angle(energy_ev, preset.spacing_a, 1)
        points = []
        for energy in energies:
            if bragg_angle(energy, preset.spacing_a, 1) is None:
                points.append(tuple(
                    BandPoint(Coverage.NO_BRAGG_ANGLE) for _ in spectrometer.crystal_labels
                ))
                continue
            _, _, traces = spectrometer.trace(context, energy, preset.spacing_a, 1, half_width_deg)
            points.append(tuple(BandPoint.from_trace(trace) for trace in traces))
        comparisons.append(BandComparison(
            index, -1.0 if center is None else math.degrees(center), tuple(points),
        ))

    def rank(comparison: BandComparison) -> tuple[bool, int, int, float]:
        band = spectrometer.reflections[comparison.reflection].published_xcs_band_ev
        precedent = band is not None and band[0] <= energy_ev <= band[1]
        return precedent, *comparison.geometry_rank()

    return energies, sorted(comparisons, key=rank, reverse=True)
