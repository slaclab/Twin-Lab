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
import shutil
import sys
import time
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

CACHE_SCHEMA = "slac-convex-decomposition/v1"

# CoACD bundles libgomp and parallelizes internally, so one worker is not one core.
# Two threads measured fastest; its own scaling is poor, so prefer parallel parts.
COACD_THREADS_PER_WORKER = 2

# Peak RSS observed on the largest 43841 parts. Workers are capped so a big cold
# build cannot drive the machine into swap.
COACD_PEAK_RSS_BYTES = 3 * 1024**3

# Spawning a worker, importing CoACD, and its size-independent MCTS setup cost about
# this much relative to per-triangle work, so progress must not be triangles alone.
PART_SETUP_COST_TRIANGLES = 15_000

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


@dataclass(frozen=True)
class PartSettings:
    """A default with per-part CoACD overrides keyed by reviewed part ref."""

    default: DecompositionSettings = DEFAULT_SETTINGS
    overrides: Mapping[str, DecompositionSettings] = field(default_factory=dict)

    def for_part(self, part_ref: str) -> DecompositionSettings:
        return self.overrides.get(part_ref, self.default)


def _as_resolver(settings: DecompositionSettings | PartSettings) -> PartSettings:
    """Accept a bare settings object or a resolver, so callers can pass either."""

    return settings if isinstance(settings, PartSettings) else PartSettings(settings)


def _settings_from_entry(
    entry: Mapping[str, Any], base: DecompositionSettings
) -> DecompositionSettings:
    return replace(
        base,
        threshold=float(entry.get("threshold", base.threshold)),
        max_hulls=int(entry.get("max_hulls", base.max_hulls)),
        seed=int(entry.get("seed", base.seed)),
    )


def part_settings_from_config(config: Mapping[str, Any] | None) -> PartSettings:
    """Build per-part settings from an inventory ``decomposition`` block.

    An override names only the fields it changes: the rest fall back to the block
    default, which in turn falls back to the module default.
    """

    if not config:
        return PartSettings()
    default = _settings_from_entry(config, DEFAULT_SETTINGS)
    overrides: dict[str, DecompositionSettings] = {}
    for entry in config.get("overrides", []):
        settings = _settings_from_entry(entry, default)
        for ref in entry.get("refs", []):
            overrides[str(ref)] = settings
    return PartSettings(default, overrides)


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


def read_part_refs(path: Path) -> list[str]:
    """Part refs in the same order and indexing as :func:`read_obj_parts`, without geometry.

    Faceless groups are dropped there too, so a ref's position here is the index a
    cache marker uses.
    """

    refs: list[str] = []
    current = path.stem
    faces = 0
    for line in path.read_text(encoding="ascii").splitlines():
        if line.startswith("o "):
            if faces:
                refs.append(current)
            current = line[2:].strip() or path.stem
            faces = 0
        elif line.startswith("f "):
            faces += 1
    if faces:
        refs.append(current)
    return refs


def invalidate_parts(cache_dir: Path, source: Path, indices: Iterable[int]) -> int:
    """Drop cached hulls for named sub-parts so the next run re-runs CoACD on them.

    The manifest goes too: it vouches for the whole source, so leaving it would make
    :func:`decompose_sources` return the stale list without dispatching anything.
    """

    part_dir = cache_dir / _safe_name(source.stem)
    if not part_dir.exists():
        return 0
    (part_dir / "manifest.json").unlink(missing_ok=True)
    removed = 0
    for index in indices:
        marker = part_dir / f"part{index:04d}.json"
        if not marker.exists():
            continue
        try:
            payload = json.loads(marker.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        item = payload.get("part")
        for name in (item or {}).get("hulls", []):
            (part_dir / name).unlink(missing_ok=True)
        marker.unlink()
        removed += 1
    return removed


def cached_hull_count(cache_dir: Path, source: Path, index: int) -> int | None:
    """Hulls recorded for one sub-part, or None when nothing is cached for it."""

    marker = cache_dir / _safe_name(source.stem) / f"part{index:04d}.json"
    if not marker.exists():
        return None
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    item = payload.get("part")
    return 0 if item is None else len(item.get("hulls", []))


def decompose_source(
    source: Path,
    cache_dir: Path,
    settings: DecompositionSettings | PartSettings = DEFAULT_SETTINGS,
) -> list[ConvexPart]:
    """Return cached convex hulls for one source OBJ, decomposing only when stale."""

    resolver = _as_resolver(settings)
    part_dir = cache_dir / _safe_name(source.stem)
    manifest_path = part_dir / "manifest.json"
    cached = _read_manifest(manifest_path, source, resolver)
    if cached is not None:
        return cached

    _clear_part_dir(part_dir, source, resolver)
    obj_parts = read_obj_parts(source)
    parts = [
        part
        for index, (ref, _, _) in enumerate(obj_parts)
        if (part := _decompose_part(source, part_dir, resolver.for_part(ref), index)) is not None
    ]
    _write_manifest(manifest_path, source, resolver, parts)
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

    # coacd.Mesh infers its parameter types from mutable zero-shaped defaults, so the
    # stub demands an unsatisfiable literal shape; runtime re-casts to these dtypes anyway.
    hulls = coacd.run_coacd(
        coacd.Mesh(
            np.asarray(vertices, dtype=np.float64),  # pyright: ignore[reportArgumentType]
            np.asarray(triangles, dtype=np.int32),  # pyright: ignore[reportArgumentType]
        ),
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


def _source_content_key(source: Path) -> dict[str, Any]:
    stat = source.stat()
    return {
        "schema": CACHE_SCHEMA,
        "source_mtime_ns": stat.st_mtime_ns,
        "source_size": stat.st_size,
        "source_sha256": _source_digest(source),
    }


def _content_matches(payload: dict[str, Any], source: Path) -> bool:
    """True when the payload was written for this source; a byte-identical rewrite bumps mtime."""

    stat = source.stat()
    if payload.get("schema") != CACHE_SCHEMA or payload.get("source_size") != stat.st_size:
        return False
    if payload.get("source_mtime_ns") == stat.st_mtime_ns:
        return True
    recorded = payload.get("source_sha256")
    return recorded is not None and recorded == _source_digest(source)


def _part_marker_key(source: Path, settings: DecompositionSettings) -> dict[str, Any]:
    return {**_source_content_key(source), "settings": settings.as_dict()}


def _source_matches(payload: dict[str, Any], source: Path, settings: DecompositionSettings) -> bool:
    """A marker matches when both the source bytes and the part's settings are unchanged."""

    return _content_matches(payload, source) and payload.get("settings") == settings.as_dict()


def _settings_signature(part_refs: Iterable[str], resolver: PartSettings) -> str:
    """Fingerprint every part's effective settings.

    An override change then invalidates only the manifest, not the resumable
    per-part markers, so unchanged parts resume instead of re-running CoACD.
    """

    payload = [[ref, resolver.for_part(ref).as_dict()] for ref in sorted(part_refs)]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


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


def _clear_part_dir(
    part_dir: Path, source: Path, settings: DecompositionSettings | PartSettings
) -> None:
    """Drop hulls from earlier generations, keeping work the markers still vouch for."""

    resolver = _as_resolver(settings)
    part_dir.mkdir(parents=True, exist_ok=True)
    keep: set[str] = set()
    for marker in sorted(part_dir.glob("part*.json")):
        part = _read_part_marker(marker, source, _marker_settings(marker, resolver))
        if part is None:
            marker.unlink()
        else:
            keep.update(hull.name for hull in part.hulls)
    for stale in part_dir.glob("*.obj"):
        if stale.name not in keep:
            stale.unlink()


def _marker_settings(marker: Path, resolver: PartSettings) -> DecompositionSettings:
    """Resolve a marker's settings from the part ref it records, before validating it."""

    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return resolver.default
    item = payload.get("part")
    ref = item.get("part_ref") if isinstance(item, dict) else None
    return resolver.for_part(ref) if ref else resolver.default


def decompose_sources(
    sources: Iterable[Path],
    cache_dir: Path,
    settings: DecompositionSettings | PartSettings = DEFAULT_SETTINGS,
    *,
    workers: int | None = None,
    progress: bool = False,
) -> dict[Path, list[ConvexPart]]:
    """Decompose many source meshes in parallel, reusing cached results.

    Work is dispatched per sub-part rather than per file, so a single large mesh
    cannot set the makespan, and the longest parts start first.
    """

    resolver = _as_resolver(settings)
    ordered = sorted({Path(source) for source in sources})
    cache_dir.mkdir(parents=True, exist_ok=True)
    results: dict[Path, list[ConvexPart]] = {}
    pending: list[Path] = []
    for source in ordered:
        cached = _read_manifest_path(cache_dir, source, resolver)
        if cached is None:
            pending.append(source)
        else:
            results[source] = cached
    if not pending:
        return {source: results[source] for source in ordered}

    jobs: list[tuple[int, Path, int, str]] = []
    for source in pending:
        _clear_part_dir(cache_dir / _safe_name(source.stem), source, resolver)
        for index, (ref, _, triangles) in enumerate(read_obj_parts(source)):
            jobs.append((len(triangles), source, index, ref))
    jobs.sort(reverse=True, key=lambda job: job[0])

    cpus = _available_cpus()
    count = workers or _default_workers(cpus)
    threads = max(1, cpus // count)

    if progress:
        total = sum(size for size, *_ in jobs)
        done = sum(1 for _, source, index, _ in jobs if _marker_exists(cache_dir, source, index))
        print(
            f"Decomposing {len(jobs)} parts across {len(pending)} of {len(ordered)} meshes "
            f"({total:,} triangles, {len(results)} meshes cached, {done} parts resumable)\n"
            f"Using {count} workers x {threads} CoACD threads on {cpus} CPUs; "
            f"results are cached, so this cost is paid once",
            flush=True,
        )

    collected: dict[Path, list[ConvexPart]] = {source: [] for source in pending}
    weights = {
        (source, index): size + PART_SETUP_COST_TRIANGLES for size, source, index, _ in jobs
    }
    bar = _Progress(len(jobs), sum(weights.values())) if progress else None
    # One task per child: CoACD retains memory per run, so recycling caps peak RSS.
    with ProcessPoolExecutor(
        max_workers=count,
        max_tasks_per_child=1,
        initializer=_limit_worker_threads,
        initargs=(threads,),
    ) as pool:
        futures = {
            pool.submit(
                _decompose_part,
                source,
                cache_dir / _safe_name(source.stem),
                resolver.for_part(ref),
                index,
            ): (source, index, size)
            for size, source, index, ref in jobs
        }
        for future in as_completed(futures):
            source, index, size = futures[future]
            part = future.result()
            if part is not None:
                collected[source].append(part)
            if bar is not None:
                bar.advance(
                    weights[(source, index)],
                    f"{source.stem}[{index}]: {len(part.hulls) if part else 0} hulls",
                )
    if bar is not None:
        bar.close()

    for source in pending:
        parts = sorted(collected[source], key=lambda part: part.part_ref)
        part_dir = cache_dir / _safe_name(source.stem)
        _write_manifest(part_dir / "manifest.json", source, resolver, parts)
        results[source] = parts
    if progress:
        hulls = sum(len(part.hulls) for parts in results.values() for part in parts)
        print(f"Decomposition complete: {len(ordered)} meshes, {hulls} hulls", flush=True)
    return {source: results[source] for source in ordered}


def _marker_exists(cache_dir: Path, source: Path, index: int) -> bool:
    return (cache_dir / _safe_name(source.stem) / f"part{index:04d}.json").exists()


def _limit_worker_threads(threads: int) -> None:
    """Runs in the child before CoACD is imported, which is when libgomp reads this."""

    os.environ["OMP_NUM_THREADS"] = str(threads)


def _available_cpus() -> int:
    """cgroup quotas and taskset affinity are invisible to os.cpu_count()."""

    if hasattr(os, "sched_getaffinity"):
        return len(os.sched_getaffinity(0))
    return os.cpu_count() or 1


def _default_workers(cpus: int) -> int:
    """Prefer separate processes: CoACD's own threads scale worse than parallel parts."""

    workers = max(2 if cpus >= 4 else 1, cpus // COACD_THREADS_PER_WORKER)
    cap = _memory_worker_cap()
    return max(1, min(workers, cap)) if cap else workers


def _memory_worker_cap() -> int | None:
    """None when the budget cannot be read, in which case CPU count decides alone."""

    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                available = int(line.split()[1]) * 1024
                return max(1, available // COACD_PEAK_RSS_BYTES)
    except (OSError, ValueError):
        return None
    return None


def _format_duration(seconds: float) -> str:
    seconds = max(int(seconds), 0)
    if seconds >= 3600:
        return f"{seconds // 3600}h{seconds % 3600 // 60:02d}m"
    if seconds >= 60:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds}s"


class _Progress:
    """Live decomposition progress: a redrawn bar on a TTY, one line per part otherwise."""

    BAR_WIDTH = 28

    def __init__(self, total_jobs: int, total_weight: int) -> None:
        self._total_jobs = total_jobs
        # Parts run largest-first, so weighting by count alone makes the bar crawl then
        # sprint; weighting by triangles alone ignores the dominant per-part setup cost.
        self._total_weight = max(total_weight, 1)
        self._jobs = 0
        self._weight = 0
        self._start = time.monotonic()
        self._live = sys.stdout.isatty()
        self._width = shutil.get_terminal_size((100, 24)).columns

    def advance(self, weight: int, label: str) -> None:
        self._jobs += 1
        self._weight += weight
        fraction = min(self._weight / self._total_weight, 1.0)
        elapsed = time.monotonic() - self._start
        if not self._live:
            print(f"  [{self._jobs}/{self._total_jobs}] {label}", flush=True)
            return
        filled = round(self.BAR_WIDTH * fraction)
        bar = "#" * filled + "-" * (self.BAR_WIDTH - filled)
        remaining = elapsed / fraction - elapsed if fraction > 0 else 0.0
        text = (
            f"  [{bar}] {fraction:5.1%}  {self._jobs}/{self._total_jobs} parts  "
            f"{_format_duration(elapsed)} elapsed, ~{_format_duration(remaining)} left"
        )
        sys.stdout.write("\r" + text[: self._width - 1].ljust(self._width - 1))
        sys.stdout.flush()

    def close(self) -> None:
        if self._live:
            sys.stdout.write("\r" + " " * (self._width - 1) + "\r")
            sys.stdout.flush()


def _read_manifest_path(
    cache_dir: Path, source: Path, settings: DecompositionSettings | PartSettings
) -> list[ConvexPart] | None:
    return _read_manifest(cache_dir / _safe_name(source.stem) / "manifest.json", source, settings)


def hull_names(item: Mapping[str, Any]) -> list[str]:
    """The hull files a manifest entry stands behind, preferring inflated ones.

    ``slac-inflate-hulls`` writes grown copies beside the originals and records them
    here, so everything downstream picks up the conservative geometry without knowing
    the pass exists, and deleting the copies puts the raw decomposition straight back.
    """

    return [str(name) for name in item.get("inflated") or item["hulls"]]


def _read_manifest(
    manifest_path: Path, source: Path, settings: DecompositionSettings | PartSettings
) -> list[ConvexPart] | None:
    resolver = _as_resolver(settings)
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not _content_matches(manifest, source):
        return None
    refs = [item["part_ref"] for item in manifest["parts"]]
    if manifest.get("parts_settings_sig") != _settings_signature(refs, resolver):
        return None
    parts = []
    for item in manifest["parts"]:
        hulls = tuple(manifest_path.parent / name for name in hull_names(item))
        if not all(hull.exists() for hull in hulls):
            return None
        parts.append(ConvexPart(source=source, part_ref=item["part_ref"], hulls=hulls))
    return parts


def _write_manifest(
    manifest_path: Path,
    source: Path,
    settings: DecompositionSettings | PartSettings,
    parts: Sequence[ConvexPart],
) -> None:
    resolver = _as_resolver(settings)
    manifest_path.write_text(
        json.dumps(
            {
                **_source_content_key(source),
                "parts_settings_sig": _settings_signature(
                    [part.part_ref for part in parts], resolver
                ),
                "source": source.as_posix(),
                "parts": [
                    {
                        "part_ref": part.part_ref,
                        "hulls": [hull.name for hull in part.hulls],
                        "settings": resolver.for_part(part.part_ref).as_dict(),
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


def _resolve_scene(source: str | Path) -> tuple[Path, dict[str, Any]]:
    """Accept either a reviewed inventory or an already prepared scene.yaml."""

    import yaml

    from .paths import resolve_repo_path

    path = resolve_repo_path(source)
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if str(document.get("schema", "")).startswith("slac-stage-cad-scene/"):
        return path, document
    from .stage_cad_viewer import prepare_stage_cad

    scene_path = prepare_stage_cad(path)
    return scene_path, yaml.safe_load(scene_path.read_text(encoding="utf-8"))


def _override_snippet(refs: Iterable[str], resolver: PartSettings) -> str:
    """The YAML to paste into the inventory so a tweak survives the next compile."""

    grouped: dict[DecompositionSettings, list[str]] = {}
    for ref in sorted(set(refs)):
        grouped.setdefault(resolver.for_part(ref), []).append(ref)
    lines = ["decomposition:", "  overrides:"]
    for settings, group in grouped.items():
        lines += [
            f"    - refs: [{', '.join(group)}]",
            f"      threshold: {settings.threshold}",
            f"      max_hulls: {settings.max_hulls}",
            f"      seed: {settings.seed}",
            "      reason: <why these parts need different hulls>",
        ]
    return "\n".join(lines)


def main() -> None:
    import argparse

    from .paths import CACHE_ROOT
    from .sdf_compiler import _build_tree, _read_decomposition_config

    parser = argparse.ArgumentParser(
        description="Regenerate CoACD convex hulls for selected reviewed parts",
        epilog="Cached hulls are reused unless --force or a changed setting invalidates them.",
    )
    parser.add_argument("source", help="Stage inventory YAML or prepared stage-cad scene.yaml")
    parser.add_argument("--part", default=None, help="Regular expression matching part refs")
    parser.add_argument("--mesh", default=None, help="Regular expression matching source OBJ stems")
    parser.add_argument("--threshold", type=float, default=None, help="CoACD concavity threshold")
    parser.add_argument("--max-hulls", type=int, default=None, help="CoACD convex hull cap")
    parser.add_argument("--seed", type=int, default=None, help="CoACD random seed")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-run CoACD even when the cache is valid; needs --part or --mesh",
    )
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument(
        "--dry-run", action="store_true", help="List the selected parts and settings, then stop"
    )
    args = parser.parse_args()

    if args.force and not (args.part or args.mesh):
        parser.error("--force needs --part or --mesh; a full rebuild takes hours")

    scene_path, scene = _resolve_scene(args.source)
    cache_dir = CACHE_ROOT / "convex-collision" / scene_path.parent.name
    base = part_settings_from_config(_read_decomposition_config(scene))
    links, _ = _build_tree(scene, scene_path)

    part_pattern = re.compile(args.part) if args.part else None
    mesh_pattern = re.compile(args.mesh) if args.mesh else None
    selected: dict[Path, list[tuple[int, str]]] = {}
    for source in sorted({mesh for link in links for _, mesh, _ in link.meshes}):
        if mesh_pattern and not mesh_pattern.search(source.stem):
            continue
        matches = [
            (index, ref)
            for index, ref in enumerate(read_part_refs(source))
            if part_pattern is None or part_pattern.search(ref)
        ]
        if matches:
            selected[source] = matches
    if not selected:
        parser.error("no reviewed part matched; check --part and --mesh")

    changes = {
        name: value
        for name, value in (
            ("threshold", args.threshold),
            ("max_hulls", args.max_hulls),
            ("seed", args.seed),
        )
        if value is not None
    }
    resolver = base
    chosen_refs = [ref for matches in selected.values() for _, ref in matches]
    if changes:
        overrides = dict(base.overrides)
        for ref in chosen_refs:
            overrides[ref] = replace(base.for_part(ref), **changes)
        resolver = PartSettings(base.default, overrides)

    print(f"{len(chosen_refs)} parts in {len(selected)} meshes under {cache_dir}")
    for source, matches in selected.items():
        for index, ref in matches:
            settings = resolver.for_part(ref)
            cached = cached_hull_count(cache_dir, source, index)
            state = "uncached" if cached is None else f"{cached} hulls"
            print(
                f"  {source.stem}[{index}] {ref}: {state}, "
                f"threshold {settings.threshold}, max_hulls {settings.max_hulls}"
            )
    if changes:
        print(
            "\nThese settings are not recorded in the reviewed inventory, so the next "
            "slac-compile-sdf will regenerate these parts at the inventory's settings.\n"
            "Paste this into the inventory's decomposition block to keep them:\n\n"
            + _override_snippet(chosen_refs, resolver)
            + "\n"
        )
    if args.dry_run:
        return

    before = {
        (source, ref): cached_hull_count(cache_dir, source, index)
        for source, matches in selected.items()
        for index, ref in matches
    }
    if args.force:
        dropped = sum(
            invalidate_parts(cache_dir, source, [index for index, _ in matches])
            for source, matches in selected.items()
        )
        print(f"Invalidated {dropped} cached parts")

    results = decompose_sources(
        selected, cache_dir, resolver, workers=args.workers, progress=True
    )
    total = 0
    for source, parts in results.items():
        for part in parts:
            if (source, part.part_ref) not in before:
                continue
            total += len(part.hulls)
            was = before[(source, part.part_ref)]
            if was != len(part.hulls):
                print(f"  {source.stem} {part.part_ref}: {was} -> {len(part.hulls)} hulls")
    print(f"{len(chosen_refs)} parts -> {total} convex hulls")
