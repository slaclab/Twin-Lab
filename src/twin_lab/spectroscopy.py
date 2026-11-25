"""Shared symmetric Bragg optics and ePix100 image sampling."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

import numpy as np
from numpy.typing import NDArray

# Reference energies: NIST KL3, KM2,3 and KM4,5, rounded to 0.1 eV.
LINES = (
    ("Fe K\u03b21,3", 7058.2),
    ("Fe K\u03b22,5", 7108.3),
    ("Mn K\u03b1 (K\u03b11)", 5898.8),
    ("Mn K\u03b21,3", 6490.6),
    ("Mn K\u03b22,5", 6535.4),
    ("Co K\u03b21,3", 7649.4),
    ("Co K\u03b22,5", 7706.0),
    ("Ni K\u03b21,3", 8264.8),
    ("Ni K\u03b22,5", 8328.7),
    ("Ti K\u03b21,3", 4931.8),
    ("Ti K\u03b22,5", 4962.3),
    ("V K\u03b1 (K\u03b11)", 4952.2),
)


@dataclass(frozen=True)
class ReflectionPreset:
    label: str
    spacing_a: float
    evidence: str = "Simulation candidate"
    source_url: str | None = None
    published_xcs_band_ev: tuple[float, float] | None = None
    reference_energies_ev: tuple[float, ...] = ()

    def matches_reference(self, energy_ev: float) -> bool:
        band = self.published_xcs_band_ev
        if band is not None and band[0] <= energy_ev <= band[1]:
            return True
        # The notes quote rounded energies and the emission presets use nominal values.
        return any(abs(energy_ev - reference) <= 2 for reference in self.reference_energies_ev)


_LATTICE_A = {"Si": 5.4310, "Ge": 5.6579}


def cubic_reflection(
    material: Literal["Si", "Ge"],
    hkl: tuple[int, int, int],
    evidence: str = "Simulation candidate",
    source_url: str | None = None,
    published_xcs_band_ev: tuple[float, float] | None = None,
    *,
    note_energy_ev: float | None = None,
) -> ReflectionPreset:
    planes = "".join(str(index) for index in hkl)
    spacing = _LATTICE_A[material] / math.sqrt(sum(index**2 for index in hkl))
    return ReflectionPreset(
        f"{material}({planes})", spacing, evidence, source_url, published_xcs_band_ev,
        reference_energies_ev=() if note_energy_ev is None else (note_energy_ev,),
    )


# The indices specify allowed diamond-cubic reflections at n=1, not mounting cuts.
# Every preset uses the same 250 mm CAD curvature.
REFLECTIONS = (
    cubic_reflection(
        "Ge", (6, 2, 0), "Published XCS Fe setup",
        "https://doi.org/10.3390/molecules29102323", (7030, 7125),
    ),
    cubic_reflection(
        "Si", (4, 4, 0), "LCLS Mn precedent (16-crystal)",
        "https://biology-lcls.slac.stanford.edu/capabilities/spectroscopy",
    ),
    cubic_reflection("Ge", (5, 1, 1)),
    cubic_reflection("Ge", (3, 3, 1)),
    cubic_reflection("Ge", (6, 4, 2)),
    cubic_reflection("Si", (5, 3, 3), "Co K\u03b2 setup notes", note_energy_ev=7649),
    cubic_reflection("Ge", (4, 4, 4), "Co valence-to-core setup notes", note_energy_ev=7705),
    cubic_reflection("Si", (4, 0, 0)),
    cubic_reflection("Si", (4, 2, 2)),
    cubic_reflection("Si", (5, 1, 1)),
    cubic_reflection("Si", (5, 3, 1)),
    cubic_reflection("Si", (4, 4, 4)),
    cubic_reflection("Si", (6, 2, 0)),
    cubic_reflection("Si", (7, 1, 1)),
    cubic_reflection("Ge", (4, 2, 2)),
    cubic_reflection("Ge", (4, 4, 0)),
    cubic_reflection("Ge", (5, 3, 1)),
    cubic_reflection("Ge", (5, 3, 3)),
    cubic_reflection("Ge", (7, 1, 1)),
)
HC_EV_ANGSTROM = 12398.419843
PIXEL_PITCH_M = 50e-6
ACTIVE_PIXELS = (768, 704)
BIN_PIXELS = 4
COLS, ROWS = (count // BIN_PIXELS for count in ACTIVE_PIXELS)
ACTIVE_SIZE_M = PIXEL_PITCH_M * np.array(ACTIVE_PIXELS)
Array = NDArray[np.float64]


def bragg_angle(energy_ev: float, spacing_a: float, order: int) -> float | None:
    """Return the glancing angle in radians, or None for an inaccessible order."""
    if not (math.isfinite(energy_ev) and energy_ev > 0):
        raise ValueError("Photon energy must be positive and finite")
    if not (math.isfinite(spacing_a) and spacing_a > 0 and order >= 1 and order % 1 == 0):
        raise ValueError("Use a positive d-spacing and a positive integer order")
    sine = order * HC_EV_ANGSTROM / (2 * spacing_a * energy_ev)
    return math.asin(sine) if sine <= 1 else None


def _dot_rows(a: Array, b: Array) -> Array:
    ax, ay, az = a.T
    bx, by, bz = b.T
    # Vectorize over samples while keeping the previous three-term sum order.
    return (ax * bx + az * bz) + ay * by


@dataclass(frozen=True)
class Aperture:
    points_m: Array
    inward_normals: Array
    area_per_sample_m2: float


def cylinder_aperture(
    origin_m: Array, axes: Array, radius_m: float,
    bounds: tuple[float, float, float, float], *, samples: tuple[int, int] = (256, 256),
) -> Aperture:
    """Sample equal-area patches on the concave side of a trimmed CAD cylinder."""
    u0, u1, v0, v1 = bounds
    nu, nv = samples
    u = u0 + (np.arange(nu) + 0.5) * (u1 - u0) / nu
    v = v0 + (np.arange(nv) + 0.5) * (v1 - v0) / nv
    x, y, z = axes
    radial = np.cos(u)[:, None] * x + np.sin(u)[:, None] * y
    grid = origin_m + radius_m * radial[:, None, :] + v[None, :, None] * z
    normals = np.broadcast_to(-radial[:, None, :], grid.shape)
    # Keep each coordinate contiguous for the Bragg check across the full aperture.
    return Aperture(
        np.asfortranarray(grid.reshape(-1, 3)),
        np.asfortranarray(normals.reshape(-1, 3)),
        radius_m * (u1 - u0) * (v1 - v0) / (nu * nv),
    )


@dataclass(frozen=True)
class Detector:
    center_m: Array
    u: Array
    v: Array
    normal: Array

    def moved(self, pose: Array) -> Detector:
        rotation = pose[:3, :3]
        return Detector(
            rotation @ self.center_m + pose[:3, 3],
            rotation @ self.u, rotation @ self.v, rotation @ self.normal,
        )


@dataclass(frozen=True)
class CrystalTrace:
    incidence_deg: tuple[float, float] | None
    accepted: int
    hits_m: Array
    uv_m: Array
    weights: Array
    bounce_m: Array
    preview_end_m: Array
    projected_uv_m: Array | None = None
    preview_start_m: Array | None = None
    # Optional smooth geometric penalty for a flat, collimated beam that misses or
    # falls outside the Bragg window. It guides search but never counts as signal.
    aim_cost: float | None = None
    geometric_uv_m: Array | None = None  # Beam axis projected from the infinite crystal plane.


class Spectrometer[PoseT](Protocol):
    @property
    def crystal_labels(self) -> tuple[str, ...]: ...

    @property
    def reflections(self) -> tuple[ReflectionPreset, ...]: ...

    @property
    def shortlist_angle_deg(self) -> float: ...

    def trace(
        self, pose: PoseT, energy_ev: float, spacing_a: float, order: int, half_width_deg: float,
        *, crystals: Sequence[int] | None = None, aim: bool = False,
    ) -> tuple[float | None, Detector, list[CrystalTrace]]: ...


def trace_crystal(
    source_m: Array, aperture: Aperture, pose: Array, detector: Detector,
    theta: float | None, half_width_rad: float, *, aim: bool = False,
) -> CrystalTrace:
    """Trace to the finite front face, in detector-local coordinates.

    The surface normal is also the lattice-plane normal (symmetric cut).
    """
    rotation, translation = pose[:3, :3], pose[:3, 3]
    source_local = rotation.T @ (source_m - translation)
    delta = aperture.points_m - source_local
    distance2 = _dot_rows(delta, delta)
    safe = distance2 > 1e-18
    distance = np.sqrt(np.where(safe, distance2, 1))
    # Normalize the scalar incidence first; only accepted samples need unit vectors.
    sine = -_dot_rows(delta, aperture.inward_normals) / distance
    front = safe & (sine > 0)
    incidence: tuple[float, float] | None = None
    if np.any(front):
        visible = sine[front].clip(0, 1)
        incidence = (
            math.degrees(math.asin(float(visible.min()))),
            math.degrees(math.asin(float(visible.max()))),
        )
    if theta is None:
        accepted = np.empty(0, dtype=np.intp)
    else:
        low = math.sin(max(0.0, theta - half_width_rad))
        high = math.sin(min(math.pi / 2, theta + half_width_rad))
        accepted = np.flatnonzero(front & (sine >= low) & (sine <= high + 1e-15))
    bounce = aperture.points_m[accepted] @ rotation.T + translation
    outgoing_local = (
        delta[accepted] / distance[accepted, None]
        + 2 * sine[accepted, None] * aperture.inward_normals[accepted]
    )
    outgoing = outgoing_local @ rotation.T
    denom = outgoing @ detector.normal
    time = ((detector.center_m - bounce) @ detector.normal) / np.where(denom < -1e-10, denom, 1)
    forward = (denom < -1e-10) & (time > 0)
    plane = bounce + time[:, None] * outgoing
    relative = plane - detector.center_m
    uv = relative @ np.stack((detector.u, detector.v), axis=1)
    inside = forward & np.all(np.abs(uv) < ACTIVE_SIZE_M / 2, axis=1)
    # dOmega/(4 pi) weights an isotropic point source without firing rays into empty space.
    weight = aperture.area_per_sample_m2 * sine[accepted] / (4 * math.pi * distance2[accepted])
    preview = np.flatnonzero(inside) if np.any(inside) else np.arange(len(accepted))
    keep = preview[np.linspace(0, len(preview) - 1, min(len(preview), 12), dtype=int)]
    length = np.where(forward, np.minimum(time, 0.35), 0.15)
    return CrystalTrace(
        incidence, len(accepted), plane[inside], uv[inside], weight[inside],
        bounce[keep], (bounce + length[:, None] * outgoing)[keep],
        uv[forward] if aim else None, np.broadcast_to(source_m, bounce[keep].shape),
    )


def detector_image(traces: list[CrystalTrace]) -> tuple[Array, Array | None, Array | None]:
    uv = np.concatenate([trace.uv_m for trace in traces])
    weights = np.concatenate([trace.weights for trace in traces])
    image = np.zeros((ROWS, COLS))
    if not len(weights):
        return image, None, None
    indices = ((uv + ACTIVE_SIZE_M / 2) / (BIN_PIXELS * PIXEL_PITCH_M)).astype(int)
    np.add.at(image, (indices[:, 1].clip(0, ROWS - 1), indices[:, 0].clip(0, COLS - 1)), weights)
    centroid = np.average(uv, axis=0, weights=weights)
    rms = np.sqrt(np.average((uv - centroid) ** 2, axis=0, weights=weights))
    return image, centroid * 1000, rms * 1000
