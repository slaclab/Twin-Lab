"""Discoverable CAD revisions and their verified geometry artifact relationships."""

from __future__ import annotations

import errno
import json
import os
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .artifacts import file_sha256, install_bundle
from .paths import CACHE_ROOT, REPOSITORY_ROOT, resolve_repo_path

CATALOG_SCHEMA = "twin-lab-cad-revision/v1"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _directory(revision: str, root: Path) -> Path:
    match = re.fullmatch(r"([a-z0-9][a-z0-9_-]*)-([a-f0-9]{8,64})", revision)
    if match is None:
        raise ValueError("Invalid CAD revision ID")
    if len(match.group(2)) < 64:
        choices = list((root / "cad" / "revisions").glob(f"{revision}*"))
        if len(choices) != 1:
            raise ValueError("CAD revision selector is unknown or ambiguous; use its full ID")
        return choices[0]
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
    pointer = _lfs_oid(source)
    slug = re.sub(r"[^a-z0-9]+", "-", assembly.lower()).strip("-")
    if not slug or len(slug) > 100:
        raise ValueError("Assembly must have a meaningful name of at most 100 characters")
    digest = pointer or file_sha256(source)
    revision = f"{slug}-{digest}"
    destination = _directory(revision, root)
    if destination.exists():
        return read_revision(revision, root=root)
    if pointer is not None:
        raise ValueError("Ingest requires STEP contents, not a Git LFS pointer")
    if parent is not None:
        previous = read_revision(parent, root=root)
        if previous["assembly"] != assembly:
            raise ValueError("Parent revision belongs to a different assembly")
        parent = previous["revision_id"]
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
    from .collision_artifacts import _lfs_oid

    directory = _directory(revision, root)
    revision = directory.name
    record = json.loads((directory / "revision.json").read_text(encoding="utf-8"))
    if record.get("schema") != CATALOG_SCHEMA or record.get("revision_id") != revision:
        raise ValueError("Invalid CAD revision metadata")
    if revision.rsplit("-", 1)[1] != record["step"]["sha256"]:
        raise ValueError("Catalog revision ID does not match its STEP checksum")
    step = _local(record["step"]["path"], root)
    if (_lfs_oid(step) or file_sha256(step)) != record["step"]["sha256"]:
        raise ValueError(f"Catalog STEP checksum mismatch: {revision}")
    bundles = []
    for path in sorted((directory / "bundles").glob("*.json")):
        binding = json.loads(path.read_text(encoding="utf-8"))
        if binding.get("step_sha256") != record["step"]["sha256"]:
            raise ValueError("Catalog bundle belongs to a different STEP")
        reference = binding["reference"]
        if reference.get("inputs", {}).get("files", {}).get("source_step") != (
            record["step"]["sha256"]
        ) or reference.get("bundle_id") != binding["bundle_id"]:
            raise ValueError("Catalog bundle reference does not match its STEP binding")
        binding["catalog_path"] = path.relative_to(root).as_posix()
        bundles.append(binding)
    return {
        **record, "selector": f"{revision.rsplit('-', 1)[0]}-{record['step']['sha256'][:12]}",
        "status": "cached" if bundles else "awaiting_review", "bundles": bundles,
    }


def list_revisions(
    *, root: Path = REPOSITORY_ROOT, assembly: str | None = None,
) -> list[dict[str, Any]]:
    revisions = []
    for path in sorted((root / "cad" / "revisions").glob("*/revision.json")):
        try:
            record = read_revision(path.parent.name, root=root)
        except (OSError, ValueError, KeyError) as error:
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                record = {"revision_id": path.parent.name, "assembly": None}
            record = {**record, "status": "invalid", "bundles": [], "error": str(error)}
        if assembly is None or record["assembly"] == assembly:
            revisions.append(record)
    return revisions


def revision_metadata(record: dict[str, Any]) -> dict[str, Any]:
    return {key: record[key] for key in (
        "revision_id", "assembly", "assembly_name", "ingested_at", "uploaded_at",
        "timestamp_basis", "original_filename", "parent_revision", "step",
    )}


def register_bundle(
    inventory: Path, reference: Path, *, root: Path = REPOSITORY_ROOT,
    assembly: str | None = None, name: str | None = None,
    parent: str | None = None, store: Path | None = None,
) -> dict[str, Any]:
    """Verify a bundle and persist an explicit, hash-bound STEP/cache relationship."""
    import yaml

    from .collision_artifacts import resolve_runtime, write_reference

    data = yaml.safe_load(inventory.read_text(encoding="utf-8"))
    descriptor = json.loads(reference.read_text(encoding="utf-8"))
    embedded = descriptor.get("cad", {})
    selected_assembly = assembly or embedded.get("assembly") or data.get(
        "subassembly", {}
    ).get("name") or inventory.name.removesuffix(".inventory.yaml")
    step = resolve_repo_path(data["source_step"], relative_to=inventory.parent)
    resolve_runtime(inventory, reference=reference, store=store)
    record = ingest_step(
        step, selected_assembly, root=root, parent=parent,
        name=name or embedded.get("assembly_name"), existing=not bool(embedded),
    )
    if descriptor["inputs"]["files"]["source_step"] != record["step"]["sha256"]:
        raise ValueError("Bundle is not tied to this STEP checksum")
    descriptor["cad"] = revision_metadata(record)
    directory = _directory(record["revision_id"], root) / "bundles"
    directory.mkdir(exist_ok=True)
    destination = directory / f"{descriptor['bundle_id']}.json"
    if destination.exists():
        binding = json.loads(destination.read_text(encoding="utf-8"))
        if binding["reference"]["sha256"] != descriptor["sha256"]:
            raise ValueError("An existing bundle ID cannot be rebound to another archive")
        if binding["reference"] != descriptor:
            binding["reference"] = descriptor
            binding["updated_at"] = _now()
            write_reference(destination, binding)
        return read_revision(record["revision_id"], root=root)
    binding = {
        "schema": "twin-lab-cad-bundle-binding/v1",
        "bundle_id": descriptor["bundle_id"], "step_sha256": record["step"]["sha256"],
        "bound_at": _now(), "collision_mode": descriptor["inputs"]["collision_mode"],
        "reference": descriptor,
    }
    write_reference(destination, binding)
    return read_revision(record["revision_id"], root=root)


def resolve_revision_runtime(
    revision: str, *, bundle_id: str | None = None, root: Path = REPOSITORY_ROOT,
    store: Path | None = None, offline: bool = False,
) -> Path:
    from .collision_artifacts import validate_runtime

    record = read_revision(revision, root=root)
    choices = record["bundles"]
    if bundle_id is not None:
        choices = [item for item in choices if item["bundle_id"] == bundle_id]
    if not choices:
        raise ValueError("CAD revision has no matching verified bundle; review and build it first")
    if len(choices) != 1:
        raise ValueError("CAD revision has multiple bundles; select an exact --bundle ID")
    installed = install_bundle(
        choices[0]["reference"], store or CACHE_ROOT / "artifacts", offline=offline,
    )
    validate_runtime(installed)
    return installed


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest")
    ingest.add_argument("step", type=Path)
    ingest.add_argument("--assembly", required=True)
    ingest.add_argument("--name")
    ingest.add_argument("--parent")
    register = commands.add_parser("register")
    register.add_argument("inventory", type=Path)
    register.add_argument("--reference", type=Path, required=True)
    register.add_argument("--assembly")
    register.add_argument("--name")
    listing = commands.add_parser("list")
    listing.add_argument("--assembly")
    listing.add_argument("--json", action="store_true")
    show = commands.add_parser("show")
    show.add_argument("revision")
    verify = commands.add_parser("verify")
    verify.add_argument("revision")
    verify.add_argument("--bundle")
    verify.add_argument("--offline", action="store_true")
    compare = commands.add_parser("compare")
    compare.add_argument("old_revision")
    compare.add_argument("new_revision")
    args = parser.parse_args()
    try:
        if args.command == "ingest":
            record = ingest_step(
                args.step, args.assembly, name=args.name, parent=args.parent,
            )
            print(json.dumps(record, indent=2, sort_keys=True))
            print(
                "STEP preserved. Review/remap this revision before building its collision bundle."
            )
        elif args.command == "register":
            record = register_bundle(
                resolve_repo_path(args.inventory).resolve(), args.reference,
                assembly=args.assembly, name=args.name,
            )
            print(json.dumps(record, indent=2, sort_keys=True))
        elif args.command == "show":
            print(json.dumps(read_revision(args.revision), indent=2, sort_keys=True))
        elif args.command == "verify":
            installed = resolve_revision_runtime(
                args.revision, bundle_id=args.bundle, offline=args.offline,
            )
            print(f"Verified STEP and collision bundle: {installed}")
        elif args.command == "compare":
            records = [read_revision(args.old_revision), read_revision(args.new_revision)]
            for record in records:
                for binding in record["bundles"]:
                    resolve_revision_runtime(
                        record["revision_id"], bundle_id=binding["bundle_id"], offline=True,
                    )
            if any(not record["bundles"] for record in records):
                raise ValueError("Both CAD revisions need verified bundles before comparison")
            print(json.dumps({
                "verified_offline": True, "same_step": records[0]["step"]["sha256"] == (
                    records[1]["step"]["sha256"]
                ), "revisions": records,
            }, indent=2, sort_keys=True))
        else:
            records = list_revisions(assembly=args.assembly)
            if args.json:
                print(json.dumps(records, indent=2, sort_keys=True))
            else:
                for record in records:
                    print(
                        f"{record['revision_id']} | {record.get('assembly_name', 'unknown')} | "
                        f"{record.get('ingested_at', 'unknown')} | {record['status']} | "
                        f"{len(record['bundles'])} bundle(s)"
                    )
    except (OSError, ValueError, KeyError) as error:
        parser.exit(2, f"CAD catalog: {error}\n")


if __name__ == "__main__":
    main()