"""Discoverable CAD revisions and their verified geometry artifact relationships."""

from __future__ import annotations

import errno
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .artifacts import file_sha256
from .paths import REPOSITORY_ROOT

CATALOG_SCHEMA = "twin-lab-cad-revision/v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _directory(revision: str, root: Path) -> Path:
    if re.fullmatch(r"[a-z0-9][a-z0-9_-]*-[a-f0-9]{64}", revision) is None:
        raise ValueError("Invalid CAD revision ID")
    return root / "cad" / "revisions" / revision


def _local(path: str, root: Path) -> Path:
    selected = (root / path).resolve()
    if Path(path).is_absolute() or not selected.is_relative_to(root.resolve()):
        raise ValueError("Catalog paths must stay inside the repository")
    return selected


def ingest_step(
    source: Path, assembly: str, *, root: Path = REPOSITORY_ROOT,
    parent: str | None = None, name: str | None = None, existing: bool = False,
) -> dict[str, Any]:
    """Keep a managed copy of a CAD upload without replacing any prior revision."""
    from .collision_artifacts import _lfs_oid

    root = root.resolve()
    source = source.resolve()
    if source.suffix.lower() not in (".stp", ".step"):
        raise ValueError("Expected a .stp or .step file")
    if _lfs_oid(source) is not None:
        raise ValueError("Ingest requires STEP contents, not a Git LFS pointer")
    slug = re.sub(r"[^a-z0-9]+", "-", assembly.lower()).strip("-")
    if not slug or len(slug) > 100:
        raise ValueError("Assembly must have a meaningful name of at most 100 characters")
    digest = file_sha256(source)
    revision = f"{slug}-{digest}"
    destination = _directory(revision, root)
    if destination.exists():
        return read_revision(revision, root=root)
    if parent is not None:
        previous = read_revision(parent, root=root)
        if previous["assembly"] != assembly:
            raise ValueError("Parent revision belongs to a different assembly")
    destination.parent.mkdir(parents=True, exist_ok=True)
    timestamp = _now()
    record = {
        "schema": CATALOG_SCHEMA, "revision_id": revision,
        "assembly": assembly, "assembly_name": name or assembly,
        "ingested_at": timestamp, "uploaded_at": None if existing else timestamp,
        "timestamp_basis": "registered_existing" if existing else "repository_import",
        "original_filename": source.name, "parent_revision": parent,
        "step": {
            "path": (destination / "source.stp").relative_to(root).as_posix(),
            "sha256": digest, "size_bytes": source.stat().st_size,
        },
    }
    with tempfile.TemporaryDirectory(prefix=".ingest-", dir=destination.parent) as temporary:
        staging = Path(temporary) / "revision"
        staging.mkdir()
        saved = staging / "source.stp"
        shutil.copyfile(source, saved)
        if file_sha256(saved) != digest:
            raise ValueError("STEP changed during ingestion; nothing was registered")
        saved.chmod(0o444)
        (staging / "revision.json").write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8",
        )
        try:
            os.rename(staging, destination)
        except OSError as error:
            if error.errno not in (errno.EEXIST, errno.ENOTEMPTY):
                raise
    return read_revision(revision, root=root)


def read_revision(revision: str, *, root: Path = REPOSITORY_ROOT) -> dict[str, Any]:
    directory = _directory(revision, root)
    record = json.loads((directory / "revision.json").read_text(encoding="utf-8"))
    if record.get("schema") != CATALOG_SCHEMA or record.get("revision_id") != revision:
        raise ValueError("Invalid CAD revision metadata")
    step = _local(record["step"]["path"], root)
    if step.is_symlink() or file_sha256(step) != record["step"]["sha256"]:
        raise ValueError(f"Catalog STEP checksum mismatch: {revision}")
    bundles = []
    for path in sorted((directory / "bundles").glob("*.json")):
        binding = json.loads(path.read_text(encoding="utf-8"))
        if binding.get("step_sha256") != record["step"]["sha256"]:
            raise ValueError("Catalog bundle belongs to a different STEP")
        bundles.append(binding)
    return {**record, "status": "cached" if bundles else "awaiting_review", "bundles": bundles}


def list_revisions(
    *, root: Path = REPOSITORY_ROOT, assembly: str | None = None,
) -> list[dict[str, Any]]:
    revisions = []
    for path in sorted((root / "cad" / "revisions").glob("*/revision.json")):
        record = read_revision(path.parent.name, root=root)
        if assembly is None or record["assembly"] == assembly:
            revisions.append(record)
    return revisions