"""Single-energy, symmetric Bragg ray tracing for the 95835 ePix100."""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

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
    note_energy_ev: float | None = None

    def matches_reference(self, energy_ev: float) -> bool:
        band = self.published_xcs_band_ev
        if band is not None and band[0] <= energy_ev <= band[1]:
            return True
        # The notes quote rounded energies and the emission presets use nominal values.
        return self.note_energy_ev is not None and abs(energy_ev - self.note_energy_ev) <= 2


_LATTICE_A = {"Si": 5.4310, "Ge": 5.6579}


def _cubic_reflection(
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
        note_energy_ev=note_energy_ev,
    )


# The indices specify allowed diamond-cubic reflections at n=1, not mounting cuts.
# Every preset uses the same 250 mm CAD curvature.
REFLECTIONS = (
    _cubic_reflection(
        "Ge", (6, 2, 0), "Published XCS Fe setup",
        "https://doi.org/10.3390/molecules29102323", (7030, 7125),
    ),
    _cubic_reflection(
        "Si", (4, 4, 0), "LCLS Mn precedent (16-crystal)",
        "https://biology-lcls.slac.stanford.edu/capabilities/spectroscopy",
    ),
    _cubic_reflection("Ge", (5, 1, 1)),
    _cubic_reflection("Ge", (3, 3, 1)),
    _cubic_reflection("Ge", (6, 4, 2)),
    _cubic_reflection("Si", (5, 3, 3), "Co K\u03b2 setup notes", note_energy_ev=7649),
    _cubic_reflection("Ge", (4, 4, 4), "Co valence-to-core setup notes", note_energy_ev=7705),
    _cubic_reflection("Si", (4, 0, 0)),
    _cubic_reflection("Si", (4, 2, 2)),
    _cubic_reflection("Si", (5, 1, 1)),
    _cubic_reflection("Si", (5, 3, 1)),
    _cubic_reflection("Si", (4, 4, 4)),
    _cubic_reflection("Si", (6, 2, 0)),
    _cubic_reflection("Si", (7, 1, 1)),
    _cubic_reflection("Ge", (4, 2, 2)),
    _cubic_reflection("Ge", (4, 4, 0)),
    _cubic_reflection("Ge", (5, 3, 1)),
    _cubic_reflection("Ge", (5, 3, 3)),
    _cubic_reflection("Ge", (7, 1, 1)),
)
HC_EV_ANGSTROM = 12398.419843
IP_M = np.zeros(3)
PIXEL_PITCH_M = 50e-6
ACTIVE_PIXELS = (768, 704)
BIN_PIXELS = 4
COLS, ROWS = (count // BIN_PIXELS for count in ACTIVE_PIXELS)
ACTIVE_SIZE_M = PIXEL_PITCH_M * np.array(ACTIVE_PIXELS)
MODEL = "DSG-000095835"
CRYSTAL_INDICES = tuple(range(4))
CHIP = "REF__Chip__sa39154207"
CRYSTAL = "REF__XRStech__CylinderCrystalAnalyzer_XPP_L2SI"

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
        uv[forward] if aim else None,
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


def load_apertures() -> tuple[list[Aperture], Detector]:
    """Resolve the optics on their reviewed moving bodies, not the alternate assemblies."""
    import yaml
    from build import CACHE, HERE, RECIPE, read_shape
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepGProp import BRepGProp
    from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    review = yaml.safe_load(RECIPE.read_text())
    stats = json.loads((CACHE / "stats.json").read_text())
    names = {
        row["ref"]: row["name"].split("_oa_")[0]
        for row in json.loads((HERE / "manifest.json").read_text())["occurrences"]
    }

    def surfaces(body: str, name: str):
        parts = review["bodies"][body]["parts"]
        refs = [part for part in parts if isinstance(part, str) and names[part] == name]
        if len(refs) != 1:
            raise ValueError(f"{body}: expected exactly one reviewed CAD part named {name}")
        explorer = TopExp_Explorer(read_shape(refs[0], review, stats), TopAbs_FACE)
        while explorer.More():
            face = TopoDS.Face_s(explorer.Current())
            props = GProp_GProps()
            BRepGProp.SurfaceProperties_s(face, props)
            sign = -1 if face.Orientation() == TopAbs_REVERSED else 1
            yield BRepAdaptor_Surface(face), props, sign
            explorer.Next()

    apertures = []
    for index in range(1, 5):
        candidates = [
            surface for surface, props, sign in surfaces(f"crystal_{index}_tilt", CRYSTAL)
            if surface.GetType() == GeomAbs_Cylinder and sign == -1 and props.Mass() > 1000
        ]
        if len(candidates) != 1:
            raise ValueError(f"Crystal {index}: expected one large concave cylindrical face")
        surface = candidates[0]
        cylinder = surface.Cylinder()
        apertures.append(cylinder_aperture(
            np.array(cylinder.Location().Coord()) / 1000,
            np.array([
                cylinder.XAxis().Direction().Coord(),
                cylinder.YAxis().Direction().Coord(),
                cylinder.Axis().Direction().Coord(),
            ]),
            cylinder.Radius() / 1000,
            (
                surface.FirstUParameter(), surface.LastUParameter(),
                surface.FirstVParameter() / 1000, surface.LastVParameter() / 1000,
            ),
        ))
    candidates = []
    for surface, props, sign in surfaces("epix100_tilt", CHIP):
        if surface.GetType() != GeomAbs_Plane or props.Mass() < 1000:
            continue
        normal = sign * np.array(surface.Plane().Axis().Direction().Coord())
        if normal[2] > 0.9:
            candidates.append((np.array(props.CentreOfMass().Coord()) / 1000, normal))
    if len(candidates) != 1:
        raise ValueError("ePix100: expected one upward-facing chip surface")
    center, normal = candidates[0]
    u = np.array([1.0, 0.0, 0.0]) - normal[0] * normal
    u /= np.linalg.norm(u)
    return apertures, Detector(center, u, np.cross(normal, u), normal)


class Spectrometer:
    """Couple the optical apertures to the same Drake poses as the stage viewer."""

    def __init__(self, scene, context):
        self.apertures, self.detector = load_apertures()
        self.plant = scene.plant
        model = self.plant.GetModelInstanceByName(MODEL)
        analyzer_bodies = [f"crystal_{index + 1}_tilt" for index in CRYSTAL_INDICES]
        self.bodies = [
            self.plant.GetBodyByName(name, model) for name in [*analyzer_bodies, "epix100_tilt"]
        ]
        self.home = [pose.inverse() for pose in self._poses(context)]

    def _poses(self, context):
        plant_context = self.plant.GetMyContextFromRoot(context)
        return [body.EvalPoseInWorld(plant_context) for body in self.bodies]

    def trace(
        self, context, energy_ev: float, spacing_a: float, order: int, half_width_deg: float,
        *, crystals: Sequence[int] = CRYSTAL_INDICES, aim: bool = False,
    ) -> tuple[float | None, Detector, list[CrystalTrace]]:
        theta = bragg_angle(energy_ev, spacing_a, order)
        if not (math.isfinite(half_width_deg) and 0 < half_width_deg < 90):
            raise ValueError("Bragg half-width must be between 0 and 90 degrees")
        relative = [
            (pose @ home).GetAsMatrix4()
            for pose, home in zip(self._poses(context), self.home, strict=True)
        ]
        detector = self.detector.moved(relative[-1])
        traces = [
            trace_crystal(
                IP_M, self.apertures[index], relative[index], detector, theta,
                math.radians(half_width_deg), aim=aim,
            )
            for index in crystals
        ]
        return theta, detector, traces
