"""Convex decomposition of reviewed CAD meshes into Drake collision geometry.

Drake's proximity engine replaces a non-convex collision mesh with its convex
hull, which spans external concavities and reports contact that cannot happen.
This module splits each cached OBJ into its reviewed parts and approximates each
part with a small set of convex hulls that Drake can use directly.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

CACHE_SCHEMA = "slac-convex-decomposition/v1"

ObjPart = tuple[str, list[tuple[float, float, float]], list[tuple[int, int, int]]]


@dataclass(frozen=True)
class DecompositionSettings:
    """CoACD parameters recorded in the cache so stale hulls are rebuilt."""

    threshold: float = 0.05
    max_hulls: int = 32
    seed: int = 0

    def as_dict(self) -> dict[str, float | int]:
        return {"threshold": self.threshold, "max_hulls": self.max_hulls, "seed": self.seed}


@dataclass(frozen=True)
class ConvexPart:
    """One reviewed part and the convex hulls that approximate it."""

    source: Path
    part_ref: str
    hulls: tuple[Path, ...]


DEFAULT_SETTINGS = DecompositionSettings()


def read_obj_parts(path: Path) -> list[ObjPart]:
    """Split one cached OBJ into its ``o``-delimited parts with local vertex indices."""

    vertices: list[tuple[float, float, float]] = []
    groups: list[tuple[str, list[tuple[int, int, int]]]] = []
    current = path.stem
    triangles: list[tuple[int, int, int]] = []
    for line in path.read_text(encoding="ascii").splitlines():
        if line.startswith("v "):
            x, y, z = (float(value) for value in line[2:].split())
            vertices.append((x, y, z))
        elif line.startswith("o "):
            if triangles:
                groups.append((current, triangles))
            current = line[2:].strip() or path.stem
            triangles = []
        elif line.startswith("f "):
            a, b, c = (int(value.split("/")[0]) - 1 for value in line[2:].split())
            triangles.append((a, b, c))
    if triangles:
        groups.append((current, triangles))

    parts = []
    for reference, group_triangles in groups:
        used = sorted({index for triangle in group_triangles for index in triangle})
        remap = {old: new for new, old in enumerate(used)}
        parts.append(
            (
                reference,
                [vertices[index] for index in used],
                [(remap[a], remap[b], remap[c]) for a, b, c in group_triangles],
            )
        )
    return parts


def decompose_source(
    source: Path,
    cache_dir: Path,
    settings: DecompositionSettings = DEFAULT_SETTINGS,
) -> list[ConvexPart]:
    """Return cached convex hulls for one source OBJ, decomposing only when stale."""

    part_dir = cache_dir / _safe_name(source.stem)
    manifest_path = part_dir / "manifest.json"
    cached = _read_manifest(manifest_path, source, settings)
    if cached is not None:
        return cached

    _clear_part_dir(part_dir, source, settings)
    parts = [
        part
        for index in range(len(read_obj_parts(source)))
        if (part := _decompose_part(source, part_dir, settings, index)) is not None
    ]
    _write_manifest(manifest_path, source, settings, parts)
    return parts


def _decompose_part(
    source: Path,
    part_dir: Path,
    settings: DecompositionSettings,
    index: int,
) -> ConvexPart | None:
    """Decompose a single sub-part; this is the unit of parallel work."""

    import coacd
    import numpy as np

    marker = part_dir / f"part{index:04d}.json"
    resumed = _read_part_marker(marker, source, settings)
    if resumed is not None:
        return resumed

    coacd.set_log_level("error")
    reference, vertices, triangles = read_obj_parts(source)[index]
    if len(vertices) < 4 or not triangles:
        _write_part_marker(marker, source, settings, None)
        return None

    hulls = coacd.run_coacd(
        coacd.Mesh(np.asarray(vertices, dtype=float), np.asarray(triangles, dtype=int)),
        threshold=settings.threshold,
        max_convex_hull=settings.max_hulls,
        seed=settings.seed,
    )
    written: list[Path] = []
    for hull_index, (hull_vertices, hull_faces) in enumerate(hulls):
        hull_path = part_dir / f"{_safe_name(reference)}_hull{hull_index:03d}.obj"
        _write_obj(hull_path, hull_vertices, hull_faces)
        written.append(hull_path)
    if not written:
        _write_part_marker(marker, source, settings, None)
        return None
    part = ConvexPart(source=source, part_ref=reference, hulls=tuple(written))
    _write_part_marker(marker, source, settings, part)
    return part


def _source_digest(source: Path) -> str:
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _part_marker_key(source: Path, settings: DecompositionSettings) -> dict[str, Any]:
    stat = source.stat()
    return {
        "schema": CACHE_SCHEMA,
        "source_mtime_ns": stat.st_mtime_ns,
        "source_size": stat.st_size,
        "settings": settings.as_dict(),
        "source_sha256": _source_digest(source),
    }


def _source_matches(payload: dict[str, Any], source: Path, settings: DecompositionSettings) -> bool:
    """Accept an entry whose source was rewritten byte-for-byte; re-tessellation bumps mtime."""

    stat = source.stat()
    if payload.get("schema") != CACHE_SCHEMA or payload.get("settings") != settings.as_dict():
        return False
    if payload.get("source_size") != stat.st_size:
        return False
    if payload.get("source_mtime_ns") == stat.st_mtime_ns:
        return True
    recorded = payload.get("source_sha256")
    return recorded is not None and recorded == _source_digest(source)


def _write_part_marker(
    marker: Path, source: Path, settings: DecompositionSettings, part: ConvexPart | None
) -> None:
    """Record one finished sub-part so a killed build resumes instead of restarting."""

    payload = _part_marker_key(source, settings)
    payload["part"] = (
        None
        if part is None
        else {"part_ref": part.part_ref, "hulls": [hull.name for hull in part.hulls]}
    )
    marker.write_text(json.dumps(payload), encoding="utf-8")


def _read_part_marker(
    marker: Path, source: Path, settings: DecompositionSettings
) -> ConvexPart | None:
    if not marker.exists():
        return None
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not _source_matches(payload, source, settings):
        return None
    item = payload.get("part")
    if item is None:
        return None
    hulls = tuple(marker.parent / name for name in item["hulls"])
    if not all(hull.exists() for hull in hulls):
        return None
    return ConvexPart(source=source, part_ref=item["part_ref"], hulls=hulls)


def _clear_part_dir(part_dir: Path, source: Path, settings: DecompositionSettings) -> None:
    """Drop hulls from earlier generations, keeping work the markers still vouch for."""

    part_dir.mkdir(parents=True, exist_ok=True)
    keep: set[str] = set()
    for marker in sorted(part_dir.glob("part*.json")):
        part = _read_part_marker(marker, source, settings)
        if part is None:
            marker.unlink()
        else:
            keep.update(hull.name for hull in part.hulls)
    for stale in part_dir.glob("*.obj"):
        if stale.name not in keep:
            stale.unlink()


def decompose_sources(
    sources: Iterable[Path],
    cache_dir: Path,
    settings: DecompositionSettings = DEFAULT_SETTINGS,
    *,
    workers: int | None = None,
    progress: bool = False,
) -> dict[Path, list[ConvexPart]]:
    """Decompose many source meshes in parallel, reusing cached results.

    Work is dispatched per sub-part rather than per file, so a single large mesh
    cannot set the makespan, and the longest parts start first.
    """

    ordered = sorted({Path(source) for source in sources})
    cache_dir.mkdir(parents=True, exist_ok=True)
    results: dict[Path, list[ConvexPart]] = {}
    pending: list[Path] = []
    for source in ordered:
        cached = _read_manifest_path(cache_dir, source, settings)
        if cached is None:
            pending.append(source)
        else:
            results[source] = cached
    if not pending:
        return {source: results[source] for source in ordered}

    jobs: list[tuple[int, Path, int]] = []
    for source in pending:
        _clear_part_dir(cache_dir / _safe_name(source.stem), source, settings)
        for index, (_, _, triangles) in enumerate(read_obj_parts(source)):
            jobs.append((len(triangles), source, index))
    jobs.sort(reverse=True, key=lambda job: job[0])

    if progress:
        total = sum(size for size, _, _ in jobs)
        done = sum(1 for _, source, index in jobs if _marker_exists(cache_dir, source, index))
        print(
            f"Decomposing {len(jobs)} parts across {len(pending)} of {len(ordered)} meshes "
            f"({total:,} triangles, {len(results)} meshes cached, {done} parts resumable)",
            flush=True,
        )

    count = workers or min(8, os.cpu_count() or 1)
    collected: dict[Path, list[ConvexPart]] = {source: [] for source in pending}
    # One task per child: CoACD retains memory per run, so recycling caps peak RSS.
    with ProcessPoolExecutor(max_workers=count, max_tasks_per_child=1) as pool:
        futures = {
            pool.submit(
                _decompose_part, source, cache_dir / _safe_name(source.stem), settings, index
            ): (source, index)
            for _, source, index in jobs
        }
        for finished, future in enumerate(as_completed(futures), start=1):
            source, index = futures[future]
            part = future.result()
            if part is not None:
                collected[source].append(part)
            if progress:
                hulls = len(part.hulls) if part else 0
                print(
                    f"  [{finished}/{len(jobs)}] {source.stem}[{index}]: {hulls} hulls",
                    flush=True,
                )

    for source in pending:
        parts = sorted(collected[source], key=lambda part: part.part_ref)
        part_dir = cache_dir / _safe_name(source.stem)
        _write_manifest(part_dir / "manifest.json", source, settings, parts)
        results[source] = parts
    if progress:
        hulls = sum(len(part.hulls) for parts in results.values() for part in parts)
        print(f"Decomposition complete: {len(ordered)} meshes, {hulls} hulls", flush=True)
    return {source: results[source] for source in ordered}


def _marker_exists(cache_dir: Path, source: Path, index: int) -> bool:
    return (cache_dir / _safe_name(source.stem) / f"part{index:04d}.json").exists()


def _read_manifest_path(
    cache_dir: Path, source: Path, settings: DecompositionSettings
) -> list[ConvexPart] | None:
    return _read_manifest(cache_dir / _safe_name(source.stem) / "manifest.json", source, settings)


def _read_manifest(
    manifest_path: Path, source: Path, settings: DecompositionSettings
) -> list[ConvexPart] | None:
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not _source_matches(manifest, source, settings):
        return None
    parts = []
    for item in manifest["parts"]:
        hulls = tuple(manifest_path.parent / name for name in item["hulls"])
        if not all(hull.exists() for hull in hulls):
            return None
        parts.append(ConvexPart(source=source, part_ref=item["part_ref"], hulls=hulls))
    return parts


def _write_manifest(
    manifest_path: Path,
    source: Path,
    settings: DecompositionSettings,
    parts: Sequence[ConvexPart],
) -> None:
    manifest_path.write_text(
        json.dumps(
            {
                **_part_marker_key(source, settings),
                "source": source.as_posix(),
                "parts": [
                    {
                        "part_ref": part.part_ref,
                        "hulls": [hull.name for hull in part.hulls],
                    }
                    for part in parts
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_obj(output: Path, vertices, faces) -> None:
    lines = [f"v {x:.9g} {y:.9g} {z:.9g}" for x, y, z in vertices]
    lines.extend(f"f {int(a) + 1} {int(b) + 1} {int(c) + 1}" for a, b, c in faces)
    output.write_text("\n".join(lines) + "\n", encoding="ascii")


def _safe_name(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "_", value).strip("_").lower() or "part"


def main() -> None:
    import argparse

    from .paths import CACHE_ROOT

    parser = argparse.ArgumentParser(description="Convex-decompose cached stage CAD meshes")
    parser.add_argument("meshes", nargs="+", help="Cached OBJ files to decompose")
    parser.add_argument("--threshold", type=float, default=0.05)
    parser.add_argument("--max-hulls", type=int, default=32)
    parser.add_argument("--workers", type=int, default=None)
    args = parser.parse_args()

    settings = replace(DEFAULT_SETTINGS, threshold=args.threshold, max_hulls=args.max_hulls)
    results = decompose_sources(
        [Path(mesh) for mesh in args.meshes],
        CACHE_ROOT / "convex-collision",
        settings,
        workers=args.workers,
        progress=True,
    )
    total = sum(len(part.hulls) for parts in results.values() for part in parts)
    print(f"{len(results)} meshes -> {total} convex hulls")
