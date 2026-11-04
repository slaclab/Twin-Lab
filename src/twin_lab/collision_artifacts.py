"""Capture and resolve the complete portable inputs of a collision review."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import xml.parsers.expat as expat
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import yaml

from .artifacts import create_bundle, file_sha256, install_bundle
from .paths import (
    CACHE_ROOT,
    EXPORT_ROOT,
    REPOSITORY_ROOT,
    resolve_repo_path,
    review_artifact_stem,
)

RUNTIME_SCHEMA = "twin-lab-collision-runtime/v2"
SUPPORTED_RUNTIME_SCHEMAS = {"twin-lab-collision-runtime/v1", RUNTIME_SCHEMA}
SIMULATION_SCHEMA = "twin-lab-simulation-snapshot/v1"


def _lfs_oid(path: Path) -> str | None:
    import re

    if path.stat().st_size > 1024:
        return None
    content = path.read_bytes()
    if not content.startswith(b"version https://git-lfs.github.com/spec/v1\n"):
        return None
    for line in content.splitlines():
        match = re.fullmatch(rb"oid sha256:([a-f0-9]{64})", line)
        if match is not None:
            return match.group(1).decode("ascii")
    raise ValueError(f"Invalid Git LFS pointer: {path.name}")


def reference_path(inventory: Path) -> Path:
    name = inventory.name.removesuffix(".inventory.yaml").removesuffix(".kinematics.yaml")
    return inventory.with_name(f"{name}.artifacts.json")


def inventory_inputs(inventory: Path, collision_mode: str) -> dict[str, Any]:
    data = yaml.safe_load(inventory.read_text(encoding="utf-8"))
    files = {"inventory": file_sha256(inventory)}
    for key in ("source_step", "cad_manifest", "stage_catalog", "selection_review"):
        if key in data:
            path = resolve_repo_path(data[key], relative_to=inventory.parent)
            files[key] = (_lfs_oid(path) or file_sha256(path)) if key == "source_step" else (
                file_sha256(path)
            )
    for index, attachment in enumerate(data.get("supplemental_attachments", [])):
        path = resolve_repo_path(attachment["mesh"], relative_to=inventory.parent)
        files[f"supplement:{index}"] = file_sha256(path)
    return {"runtime": RUNTIME_SCHEMA, "collision_mode": collision_mode, "files": files}


def validate_inputs(inventory: Path, reference: dict[str, Any]) -> None:
    recorded = reference.get("inputs", {})
    if recorded.get("runtime") not in SUPPORTED_RUNTIME_SCHEMAS:
        raise ValueError("Unsupported collision artifact runtime; build a compatible bundle")
    current = inventory_inputs(inventory, recorded["collision_mode"])
    current["runtime"] = recorded["runtime"]
    if current != recorded:
        raise ValueError(
            "CAD or reviewed inventory differs from the pinned artifact. "
            "Build and validate a new bundle explicitly with slac-artifacts build; "
            "the previous bundle has not been changed."
        )


def _generator_versions() -> dict[str, str]:
    versions = {}
    for name in ("twin-lab", "drake", "coacd", "cadquery-ocp", "numpy"):
        try:
            versions[name] = version(name)
        except PackageNotFoundError:
            versions[name] = "unavailable"
    for name in ("stage_cad_viewer.py", "sdf_compiler.py", "convex_collision.py"):
        versions[name] = file_sha256(Path(__file__).with_name(name))
    return versions


def _snapshot_simulation(
    root: Path, inventory: Path, data: dict[str, Any], scene: dict[str, Any],
    inputs: dict[str, Any],
) -> None:
    review = root / "review"
    catalog = resolve_repo_path(data["stage_catalog"], relative_to=inventory.parent)
    shutil.copyfile(catalog, review / "stage-catalog.yaml")
    shutil.copyfile(inventory, review / "source.inventory.yaml")
    stage_types = yaml.safe_load(catalog.read_text(encoding="utf-8"))["stages"]
    for instance in data.get("stage_instances", []):
        if instance["catalog"] not in stage_types:
            raise ValueError(f"Stage {instance['ref']} has no definition in its saved catalog")
    source = resolve_repo_path(data["source_step"], relative_to=inventory.parent)
    if _lfs_oid(source) is not None:
        raise ValueError("A complete bundle requires STEP contents; run git lfs pull first")
    (root / "cad").mkdir()
    shutil.copyfile(source, root / "cad" / "source.stp")
    with (root / "package" / "joint_metadata.csv").open(encoding="utf-8") as stream:
        compiled_joints = list(csv.DictReader(stream))
    snapshot = {
        "schema": SIMULATION_SCHEMA,
        "assembly": data.get("subassembly", {}),
        "source_step_sha256": inputs["files"]["source_step"],
        "stage_catalog_sha256": inputs["files"]["stage_catalog"],
        "inventory_sha256": inputs["files"]["inventory"],
        "stage_instances": data.get("stage_instances", []),
        "motion_chains": scene.get("motion_chains", []),
        "reviewed_motion_chains": data.get("motion_chains", {}),
        "compound_motion_chains": data.get("compound_motion_chains", {}),
        "joint_limit_overrides": data.get("joint_limit_overrides", {}),
        "compiled_joints": compiled_joints,
        "dof_count": len(compiled_joints),
    }
    (review / "simulation.json").write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )


def validate_simulation_snapshot(root: Path) -> dict[str, Any]:
    review = root / "review"
    snapshot = json.loads((review / "simulation.json").read_text(encoding="utf-8"))
    if snapshot.get("schema") != SIMULATION_SCHEMA:
        raise ValueError("Unsupported simulation snapshot schema")
    for path, key in (
        (root / "cad" / "source.stp", "source_step_sha256"),
        (review / "stage-catalog.yaml", "stage_catalog_sha256"),
        (review / "source.inventory.yaml", "inventory_sha256"),
    ):
        if file_sha256(path) != snapshot[key]:
            raise ValueError(f"Simulation snapshot checksum mismatch: {path.name}")
    with (root / "package" / "joint_metadata.csv").open(encoding="utf-8") as stream:
        joints = list(csv.DictReader(stream))
    if joints != snapshot["compiled_joints"] or len(joints) != snapshot["dof_count"]:
        raise ValueError("Compiled DOFs do not match the saved simulation snapshot")
    catalog = yaml.safe_load((review / "stage-catalog.yaml").read_text(encoding="utf-8"))
    for instance in snapshot["stage_instances"]:
        if instance["catalog"] not in catalog["stages"]:
            raise ValueError("Simulation references an unknown stage catalog entry")
    return snapshot


def simulation_identity(reference: dict[str, Any]) -> dict[str, Any]:
    files = reference["inputs"]["files"]
    identity = {
        "source_step_sha256": files["source_step"],
        "stage_catalog_sha256": files["stage_catalog"],
        "inventory_sha256": files["inventory"],
        "bundle_id": reference["bundle_id"],
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "schema": "twin-lab-simulation-identity/v1",
        "simulation_id": hashlib.sha256(encoded).hexdigest(), **identity,
    }


def capture_bundle(
    inventory: Path,
    package: Path,
    scene_path: Path,
    decomposition: Path | None,
    archive: Path,
    *,
    collision_mode: str = "convex",
    accept_legacy: bool = False,
    cad_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Snapshot a validated build into portable files, leaving the build untouched."""
    from .sdf_compiler import _build_tree

    inputs = inventory_inputs(inventory, collision_mode)
    if cad_metadata is not None and cad_metadata.get("step", {}).get("sha256") != (
        inputs["files"]["source_step"]
    ):
        raise ValueError("CAD metadata belongs to a different STEP checksum")
    scene = yaml.safe_load(scene_path.read_text(encoding="utf-8"))
    recorded = scene.get("source_fingerprints")
    if recorded != inputs["files"] and not (recorded is None and accept_legacy):
        raise ValueError(
            "Scene input fingerprints do not match this review. Build fresh geometry, "
            "or explicitly accept a manually validated legacy cache with --accept-legacy."
        )
    links, _ = _build_tree(scene, scene_path.resolve())
    used_sources = {source.resolve() for link in links for _, source, _ in link.meshes}
    used_sources.update(
        source.resolve() for link in links for _, source in link.collision_only_meshes
    )
    if not list(package.glob("*.sdf")) or not (package / "joint_metadata.csv").is_file():
        raise ValueError("Collision package is incomplete")
    data = yaml.safe_load(inventory.read_text(encoding="utf-8"))
    scene_dir = scene_path.resolve().parent
    with tempfile.TemporaryDirectory(prefix="twin-lab-bundle-") as temporary:
        root = Path(temporary)
        shutil.copytree(package, root / "package")
        tessellations = root / "tessellations"
        tessellations.mkdir()
        for mesh in scene_dir.rglob("*.obj"):
            target = tessellations / mesh.relative_to(scene_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(mesh, target)
        review = root / "review"
        review.mkdir()
        bundled_inventory = {
            **data, "cad_manifest": "manifest.json", "stage_catalog": "stage-catalog.yaml",
            "source_step": "../cad/source.stp",
        }
        (review / "inventory.yaml").write_text(
            yaml.safe_dump(bundled_inventory, sort_keys=False), encoding="utf-8"
        )
        manifest_path = resolve_repo_path(data["cad_manifest"], relative_to=inventory.parent)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.pop("source_step", None)
        (review / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        _snapshot_simulation(root, inventory, data, scene, inputs)
        if decomposition is not None and decomposition.is_dir():
            destination = root / "decomposition"
            for source_manifest in sorted(decomposition.rglob("manifest.json")):
                content = json.loads(source_manifest.read_text(encoding="utf-8"))
                source = Path(content["source"])
                if not source.is_absolute():
                    source = (source_manifest.parent / source).resolve()
                if source.resolve() not in used_sources:
                    continue
                if source.is_relative_to(scene_dir):
                    mesh_target = tessellations / source.relative_to(scene_dir)
                else:
                    mesh_target = tessellations / "external" / f"{file_sha256(source)}.obj"
                    mesh_target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, mesh_target)
                target = destination / source_manifest.relative_to(decomposition)
                target.parent.mkdir(parents=True, exist_ok=True)
                content["source"] = Path(os.path.relpath(mesh_target, target.parent)).as_posix()
                for part in content.get("parts", []):
                    for name in part["hulls"]:
                        if Path(name).name != name:
                            raise ValueError("Hull paths must be local filenames")
                        shutil.copy2(source_manifest.parent / name, target.parent / name)
                audit = source_manifest.parent / "audit.npz"
                if audit.exists():
                    shutil.copy2(audit, target.parent / audit.name)
                target.write_text(json.dumps(content, sort_keys=True), encoding="utf-8")
        if collision_mode == "convex" and not (root / "decomposition").is_dir():
            raise ValueError("Convex bundles require decomposition data for CAD verification")
        (root / "runtime.json").write_text(
            json.dumps({
                "schema": RUNTIME_SCHEMA, "collision_mode": collision_mode,
                "tessellation_deflection_mm": scene.get("linear_deflection_mm"),
                "generators": _generator_versions(),
            }, indent=2),
            encoding="utf-8",
        )
        validate_runtime(root)
        return create_bundle(
            root, archive, inputs=inputs,
            metadata={"cad": cad_metadata} if cad_metadata is not None else None,
        )


def validate_runtime(root: Path) -> None:
    runtime = json.loads((root / "runtime.json").read_text(encoding="utf-8"))
    if runtime.get("schema") not in SUPPORTED_RUNTIME_SCHEMAS:
        raise ValueError("Unsupported installed collision runtime")
    if runtime["schema"] == RUNTIME_SCHEMA:
        validate_simulation_snapshot(root)
    package = root / "package"
    models = [path for path in package.glob("*.sdf") if not path.stem.endswith("_matlab")]
    if len(models) != 1 or not (package / "joint_metadata.csv").is_file():
        raise ValueError("Bundle requires one collision SDF and its joint metadata")
    try:
        for path in package.glob("*.sdf"):
            builder = ET.TreeBuilder()
            parser = expat.ParserCreate()
            parser.StartElementHandler = builder.start
            parser.EndElementHandler = builder.end
            parser.CharacterDataHandler = builder.data
            with path.open("rb") as stream:
                parser.ParseFile(stream)
            tree = builder.close()
            if path == models[0] and not tree.findall(".//collision"):
                raise ValueError("Bundle SDF has no collision geometry")
            for uri in tree.findall(".//mesh/uri"):
                mesh = Path(uri.text or "")
                resolved = (package / mesh).resolve()
                if mesh.is_absolute() or not resolved.is_relative_to(package.resolve()):
                    raise ValueError("Bundle SDF must use package-local mesh paths")
                if not resolved.is_file():
                    raise ValueError(f"Bundle SDF references missing mesh: {mesh}")
    except expat.ExpatError as error:
        raise ValueError("Bundle contains invalid SDF XML") from error
    for path in (root / "decomposition").rglob("manifest.json"):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        source = Path(manifest["source"])
        resolved = (path.parent / source).resolve()
        if source.is_absolute() or not resolved.is_relative_to(root.resolve()):
            raise ValueError("Decomposition sources must stay inside the bundle")
        if not resolved.is_file():
            raise ValueError("Decomposition source tessellation is missing")
        if manifest.get("source_sha256") not in (None, file_sha256(resolved)):
            raise ValueError("Decomposition source checksum mismatch")
    for name in ("inventory.yaml", "manifest.json"):
        if not (root / "review" / name).is_file():
            raise ValueError(f"Bundle is missing review metadata: {name}")


def resolve_runtime(
    inventory: Path, *, reference: Path | None = None, offline: bool = False,
    store: Path | None = None,
) -> Path:
    """Resolve only published geometry; never invoke CAD or hull builders."""
    selected = reference or reference_path(inventory)
    if not selected.is_file():
        raise FileNotFoundError(
            f"No pinned artifact reference at {selected}. "
            "Use slac-artifacts capture for an existing validated cache, or "
            "slac-artifacts build for new CAD. Viewer startup does not build geometry."
        )
    descriptor = json.loads(selected.read_text(encoding="utf-8"))
    validate_inputs(inventory, descriptor)
    root = install_bundle(descriptor, store or CACHE_ROOT / "artifacts", offline=offline)
    runtime = json.loads((root / "runtime.json").read_text(encoding="utf-8"))
    if runtime.get("schema") not in SUPPORTED_RUNTIME_SCHEMAS:
        raise ValueError("Unsupported installed collision runtime")
    validate_runtime(root)
    return root


def build_bundle(
    inventory: Path, archive: Path, *, collision_mode: str = "convex", workers: int | None = None,
    cad_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build new CAD in an isolated workspace; failure leaves installed revisions alone."""
    from .sdf_compiler import compile_sdf_package
    from .stage_cad_viewer import prepare_stage_cad

    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    data = yaml.safe_load(inventory.read_text(encoding="utf-8"))
    step = resolve_repo_path(data["source_step"], relative_to=inventory.parent)
    if _lfs_oid(step) is not None:
        raise ValueError("An explicit CAD build needs the STEP contents; run git lfs pull first")
    before = inventory_inputs(inventory, collision_mode)
    with tempfile.TemporaryDirectory(prefix="artifact-build-", dir=CACHE_ROOT) as temporary:
        scratch = Path(temporary)
        scene = prepare_stage_cad(inventory, rebuild=True, cache_root=scratch)
        decomposition = scratch / "convex-collision" / scene.parent.name
        package = scratch / "package"
        compile_sdf_package(
            scene, package, include_collisions=True, collision_mode=collision_mode,
            neutral_visuals=True, decomposition_workers=workers,
            decomposition_dir=decomposition, archive=False,
        )
        if inventory_inputs(inventory, collision_mode) != before:
            raise ValueError("CAD review changed during the build; no reference was updated")
        return capture_bundle(
            inventory, package, scene, decomposition, archive, collision_mode=collision_mode,
            cad_metadata=cad_metadata,
        )


def write_reference(destination: Path, reference: dict[str, Any]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=destination.parent, delete=False,
    ) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(reference, stream, indent=2, sort_keys=True)
            stream.write("\n")
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    import argparse
    import re
    from urllib.parse import quote

    from .cad_catalog import ingest_step, register_bundle, revision_metadata

    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("build", "capture", "fetch", "verify", "publish"):
        command = commands.add_parser(name)
        command.add_argument("stage_inventory", type=Path)
        command.add_argument("--reference", type=Path)
        if name in ("build", "capture", "publish"):
            command.add_argument("--archive", type=Path, required=True)
        if name in ("build", "capture"):
            command.add_argument("--url", help="Published HTTPS URL; defaults to a local file URL")
            command.add_argument("--collision-mode", choices=("convex", "hull"), default="convex")
        if name == "build":
            command.add_argument("--workers", type=int)
        if name == "capture":
            command.add_argument("--package-dir", type=Path)
            command.add_argument("--scene", type=Path)
            command.add_argument("--decomposition-dir", type=Path)
            command.add_argument("--accept-legacy", action="store_true")
        if name == "publish":
            command.add_argument("--repo", required=True, help="GitHub OWNER/REPOSITORY")
            command.add_argument("--tag", required=True, help="An existing GitHub release tag")
    args = parser.parse_args()
    inventory = resolve_repo_path(args.stage_inventory).resolve()
    selected = args.reference or reference_path(inventory)
    try:
        if args.command in ("fetch", "verify"):
            root = resolve_runtime(inventory, reference=selected, offline=args.command == "verify")
            print(f"Verified collision bundle: {root}")
            return
        if args.command == "publish":
            descriptor = json.loads(selected.read_text(encoding="utf-8"))
            validate_inputs(inventory, descriptor)
            if file_sha256(args.archive) != descriptor["sha256"]:
                raise ValueError("Archive checksum does not match the selected reference")
            if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repo) is None:
                raise ValueError("--repo must be OWNER/REPOSITORY")
            subprocess.run([
                "gh", "release", "upload", args.tag, str(args.archive.resolve()),
                "--repo", args.repo,
            ], check=True)
            descriptor["url"] = (
                f"https://github.com/{args.repo}/releases/download/"
                f"{quote(args.tag, safe='')}/{quote(args.archive.name, safe='')}"
            )
            write_reference(selected, descriptor)
            register_bundle(inventory, selected, root=REPOSITORY_ROOT)
            print(f"Published without replacing existing assets. Commit {selected}")
            return
        data = yaml.safe_load(inventory.read_text(encoding="utf-8"))
        source = resolve_repo_path(data["source_step"], relative_to=inventory.parent)
        assembly = data.get("subassembly", {}).get("name") or review_artifact_stem(inventory)
        record = ingest_step(source, assembly, root=REPOSITORY_ROOT, existing=True)
        cad_metadata = revision_metadata(record)
        if args.command == "build":
            descriptor = build_bundle(
                inventory, args.archive, collision_mode=args.collision_mode, workers=args.workers,
                cad_metadata=cad_metadata,
            )
        else:
            from .sdf_compiler import package_is_current

            stem = review_artifact_stem(inventory)
            scene = args.scene or CACHE_ROOT / "stage-cad" / stem / "scene.yaml"
            package = args.package_dir or EXPORT_ROOT / f"{stem}.collision"
            if not package_is_current(
                package, scene, include_collisions=True, collision_mode=args.collision_mode,
                neutral_visuals=True,
            ):
                raise ValueError("Compiled package is stale or incomplete; build explicitly")
            descriptor = capture_bundle(
                inventory, package, scene,
                args.decomposition_dir or CACHE_ROOT / "convex-collision" / stem,
                args.archive, collision_mode=args.collision_mode, accept_legacy=args.accept_legacy,
                cad_metadata=cad_metadata,
            )
            descriptor["cad"] = cad_metadata
        root = install_bundle(descriptor, CACHE_ROOT / "artifacts")
        if args.url:
            if not args.url.startswith("https://"):
                raise ValueError("Published bundle URLs must use HTTPS")
            descriptor["url"] = args.url
        write_reference(selected, descriptor)
        register_bundle(inventory, selected, root=REPOSITORY_ROOT)
        print(f"Verified and installed: {root}")
        print(f"Artifact reference: {selected}")
        if not args.url:
            print("Local reference only. Publish the archive before sharing this reference.")
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(2, f"Artifacts: {error}\n")


if __name__ == "__main__":
    main()