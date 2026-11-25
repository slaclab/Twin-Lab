"""Portable, immutable geometry bundles selected by committed references."""

from __future__ import annotations

import errno
import gzip
import hashlib
import io
import json
import os
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

REFERENCE_SCHEMA = "twin-lab-artifact-reference/v1"
BUNDLE_SCHEMA = "twin-lab-artifact-bundle/v1"
MANIFEST_NAME = "bundle.json"


def file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _identity(manifest: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(manifest)).hexdigest()


def _validate_reference(reference: dict[str, Any]) -> None:
    if reference.get("schema") != REFERENCE_SCHEMA:
        raise ValueError("Unsupported artifact reference schema")
    for key in ("bundle_id", "sha256"):
        value = reference.get(key, "")
        if not isinstance(value, str) or len(value) != 64 or any(
            character not in "0123456789abcdef" for character in value
        ):
            raise ValueError(f"Invalid artifact {key}")


def _safe_name(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts and (
        path.as_posix() == name and "\\" not in name and ":" not in name
    )


def create_bundle(
    source: Path, archive: Path, *, inputs: dict[str, Any], metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write a reproducible bundle without replacing an existing published archive."""
    source = source.resolve()
    archive = archive.resolve()
    if source == archive or source in archive.parents:
        raise ValueError("Bundle archive must be outside its source directory")
    files = {}
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Bundle cannot contain symlinks: {path.name}")
        if path.is_file():
            name = path.relative_to(source).as_posix()
            if name == MANIFEST_NAME or not _safe_name(name):
                raise ValueError(f"Reserved or unsafe bundle path: {name}")
            files[name] = {"sha256": file_sha256(path), "size": path.stat().st_size}
    if not files:
        raise ValueError("Cannot publish an empty bundle")
    manifest = {"schema": BUNDLE_SCHEMA, "inputs": inputs, "files": files}
    if metadata is not None:
        manifest["metadata"] = metadata
    manifest_bytes = _canonical(manifest)
    archive.parent.mkdir(parents=True, exist_ok=True)
    with archive.open("xb") as output:
        try:
            with gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w") as bundle:
                    header = tarfile.TarInfo(MANIFEST_NAME)
                    header.size = len(manifest_bytes)
                    bundle.addfile(header, io.BytesIO(manifest_bytes))
                    for name, facts in files.items():
                        header = tarfile.TarInfo(name)
                        header.size = facts["size"]
                        with (source / name).open("rb") as stream:
                            bundle.addfile(header, stream)
        except BaseException:
            archive.unlink(missing_ok=True)
            raise
    return {
        "schema": REFERENCE_SCHEMA,
        "bundle_id": _identity(manifest),
        "sha256": file_sha256(archive),
        "url": archive.as_uri(),
        "inputs": inputs,
    }


def verify_bundle(directory: Path, reference: dict[str, Any]) -> dict[str, Any]:
    """Verify every file before using an installed revision, without repairing it."""
    _validate_reference(reference)
    manifest_path = directory / MANIFEST_NAME
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("Artifact checksum verification failed: missing bundle manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != BUNDLE_SCHEMA or _identity(manifest) != reference["bundle_id"]:
        raise ValueError("Artifact manifest checksum mismatch")
    if manifest.get("inputs") != reference.get("inputs"):
        raise ValueError("Artifact input manifest mismatch")
    expected = manifest["files"]
    actual = set()
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise ValueError("Artifact checksum verification failed: unexpected symlink")
        if path.is_file() and path != manifest_path:
            actual.add(path.relative_to(directory).as_posix())
    if actual != set(expected):
        raise ValueError("Artifact checksum verification failed: file set mismatch")
    for name, facts in expected.items():
        if not _safe_name(name):
            raise ValueError("Unsafe artifact path")
        path = directory / name
        if path.stat().st_size != facts["size"] or file_sha256(path) != facts["sha256"]:
            raise ValueError(f"Artifact checksum mismatch: {name}; restore this bundle explicitly")
    return manifest


def _unpack(archive: Path, destination: Path, reference: dict[str, Any]) -> None:
    with tarfile.open(archive, "r:gz") as bundle:
        first = bundle.next()
        if first is None or first.name != MANIFEST_NAME or not first.isfile():
            raise ValueError("Bundle must start with its manifest")
        if first.size > 8 * 1024 * 1024:
            raise ValueError("Bundle manifest is too large")
        stream = bundle.extractfile(first)
        if stream is None:
            raise ValueError("Missing bundle manifest")
        manifest_bytes = stream.read()
        manifest = json.loads(manifest_bytes)
        if manifest.get("schema") != BUNDLE_SCHEMA or _identity(manifest) != reference["bundle_id"]:
            raise ValueError("Artifact manifest checksum mismatch")
        (destination / MANIFEST_NAME).write_bytes(manifest_bytes)
        seen = set()
        for member in bundle:
            if member is first:
                continue
            name = member.name
            facts = manifest["files"].get(name)
            if (
                not member.isfile() or not _safe_name(name) or name in seen
                or facts is None or member.size != facts["size"]
            ):
                raise ValueError(f"Unsafe or unexpected bundle member: {name}")
            seen.add(name)
            path = destination / name
            path.parent.mkdir(parents=True, exist_ok=True)
            content = bundle.extractfile(member)
            if content is None:
                raise ValueError(f"Missing bundle member: {name}")
            with path.open("xb") as output:
                shutil.copyfileobj(content, output)
    verify_bundle(destination, reference)


def install_bundle(
    reference: dict[str, Any], store: Path, *, offline: bool = False
) -> Path:
    """Fetch, verify and atomically install a revision; never overwrite another revision."""
    _validate_reference(reference)
    store = store.resolve()
    destination = store / reference["bundle_id"]
    if destination.exists():
        if destination.is_symlink():
            raise ValueError("Artifact directory must not be a symlink")
        verify_bundle(destination, reference)
        return destination
    if offline:
        raise FileNotFoundError("Artifact is not installed; fetch it before using offline mode")
    url = reference.get("url", "")
    if urlparse(url).scheme not in ("https", "file"):
        raise ValueError("Artifact URL must use HTTPS or a local file URL")
    store.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".install-", dir=store) as temporary:
        staging = Path(temporary)
        archive = staging / "download.tar.gz"
        with urllib.request.urlopen(url, timeout=60) as response, archive.open("xb") as output:
            shutil.copyfileobj(response, output)
        if file_sha256(archive) != reference["sha256"]:
            raise ValueError("Downloaded artifact checksum mismatch")
        extracted = staging / "bundle"
        extracted.mkdir()
        _unpack(archive, extracted, reference)
        try:
            os.rename(extracted, destination)
        except OSError as error:
            if error.errno not in (errno.EEXIST, errno.ENOTEMPTY):
                raise
            verify_bundle(destination, reference)
        else:
            for path in destination.rglob("*"):
                path.chmod(0o555 if path.is_dir() else 0o444)
            destination.chmod(0o555)
    return destination