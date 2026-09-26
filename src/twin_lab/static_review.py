"""Review a name-filtered STEP assembly without motion or collision compilation."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

import yaml

from .cad_geometry import leaf_occurrences, write_group_obj
from .constraints_wizard import (
    _read_step_document,
    view_step_preview,
    write_cad_manifest,
    write_step_preview,
)
from .convex_collision import decompose_sources
from .paths import CACHE_ROOT, REPOSITORY_ROOT, resolve_repo_path, review_artifact_stem

RECIPE = REPOSITORY_ROOT / "cad/DSG-000040389/reviews/43841-static-review.yaml"
LEGACY_COMMIT = "13e023b"
FASTENER_NAME = re.compile(
    r"screw|shcs|fhcs|bhcs|setscr|bolt|washer|\bnut\b|helicoil|"
    r"heat-set insert|thrdinsert|dowelpin|\brivet\b|"
    r"selfclinchingstud|nutthumb",
    re.IGNORECASE,
)


def normalized_name(name: str) -> str:
    return re.sub(r"_oa_\d+$", "", name).casefold()


def review_cache_name(review_path: Path) -> str:
    return (
        "43841-static-review"
        if review_path.resolve() == RECIPE.resolve()
        else review_artifact_stem(review_path)
    )


def select_leaves(manifest: dict, omitted_names: dict[str, list[str]]) -> tuple[set[str], int]:
    leaves = [item for item in manifest["occurrences"] if not item["is_assembly"]]
    names = set(omitted_names)
    omitted = {str(item["ref"]) for item in leaves if normalized_name(str(item["name"])) in names}
    return omitted, len(leaves)


def _descendant_refs(manifest: dict, assembly_names: set[str]) -> set[str]:
    occurrences = manifest["occurrences"]
    roots = [
        str(item["id"])
        for item in occurrences
        if item["is_assembly"] and normalized_name(str(item["name"])) in assembly_names
    ]
    return {
        str(item["ref"])
        for item in occurrences
        if not item["is_assembly"]
        and any(str(item["id"]).startswith(f"{root}/") for root in roots)
    }


def collision_only_refs(manifest: dict, recipe: dict) -> set[str]:
    return _descendant_refs(
        manifest,
        {normalized_name(name) for name in recipe.get("collision_only_assemblies", [])},
    )


def collision_refs(manifest: dict, recipe: dict) -> set[str]:
    omitted, _, _ = review_selection(manifest, recipe)
    return {
        str(item["ref"])
        for item in manifest["occurrences"]
        if not item["is_assembly"] and item["ref"] not in omitted
    } | collision_only_refs(manifest, recipe)


def carry_review(
    previous_manifest: dict, new_manifest: dict, recipe: dict, step: Path
) -> tuple[dict, list[str]]:
    previous_names = Counter(
        normalized_name(str(item["name"]))
        for item in previous_manifest["occurrences"]
        if not item["is_assembly"]
    )
    current_names = Counter(
        normalized_name(str(item["name"]))
        for item in new_manifest["occurrences"]
        if not item["is_assembly"]
    )
    current_assemblies = {
        normalized_name(str(item["name"]))
        for item in new_manifest["occurrences"]
        if item["is_assembly"]
    }
    present = current_names.keys() | current_assemblies
    carried = copy.deepcopy(recipe)
    carried["source_sha256"] = hashlib.sha256(step.read_bytes()).hexdigest()
    carried["omitted_names"] = {
        name: reasons
        for name, reasons in carried["omitted_names"].items()
        if name in present
    }
    for key in (
        "omitted_assemblies", "omitted_components", "translucent_assemblies",
        "translucent_components", "collision_only_assemblies",
    ):
        carried[key] = [
            name for name in carried.get(key, []) if normalized_name(name) in present
        ]
    review_selection(new_manifest, carried)
    added = current_names - previous_names
    return carried, sorted(name for name, count in added.items() for _ in range(count))


def prepare_collision_meshes(
    step: Path, manifest: dict, recipe: dict, *, output_dir: Path | None = None
) -> list[Path]:
    cover_refs = collision_only_refs(manifest, recipe)
    solid_refs = collision_refs(manifest, recipe) - cover_refs
    if not solid_refs or not cover_refs:
        raise ValueError("Collision review requires visible parts and a collision-only cover")
    cache = output_dir or (
        CACHE_ROOT / recipe.get("cache_name", "43841-static-review")
        / recipe["source_sha256"][:16] / "collision"
    )
    cache.mkdir(parents=True, exist_ok=True)
    document, _, roots = _read_step_document(step)
    assert document is not None
    leaves = leaf_occurrences(roots)
    sources = []
    groups = [sorted(solid_refs)[index:index + 24] for index in range(0, len(solid_refs), 24)]
    groups.append(sorted(cover_refs))
    for index, refs in enumerate(groups):
        name = "collision_only_cover.obj" if index == len(groups) - 1 else f"batch_{index:03}.obj"
        path = cache / name
        marker = path.with_suffix(".json")
        identity = {"source_sha256": recipe["source_sha256"], "part_refs": refs}
        if not path.exists() or not marker.exists() or json.loads(marker.read_text()) != identity:
            try:
                write_group_obj(
                    [leaves[ref] for ref in refs], path, linear_deflection_mm=2.0
                )
            except ValueError as exc:
                raise ValueError(f"No collision triangles for {refs}") from exc
            marker.write_text(json.dumps(identity, indent=2) + "\n", encoding="utf-8")
        sources.append(path)
    return sources


def review_selection(manifest: dict, recipe: dict) -> tuple[set[str], set[str], int]:
    occurrences = manifest["occurrences"]
    leaves = [item for item in occurrences if not item["is_assembly"]]
    actual_names = {normalized_name(str(item["name"])) for item in occurrences}
    requested = {
        normalized_name(name)
        for key in (
            "omitted_assemblies", "omitted_components", "translucent_assemblies",
            "translucent_components", "collision_only_assemblies",
        )
        for name in recipe.get(key, [])
    }
    missing = requested - actual_names
    if missing:
        raise ValueError(f"Reviewed component names absent from STEP: {sorted(missing)}")

    omitted = _descendant_refs(
        manifest, {normalized_name(name) for name in recipe.get("omitted_assemblies", [])}
    ) | collision_only_refs(manifest, recipe)
    omitted.update(
        str(item["ref"])
        for item in leaves
        if normalized_name(str(item["name"])) in recipe["omitted_names"]
        or normalized_name(str(item["name"]))
        in {normalized_name(name) for name in recipe.get("omitted_components", [])}
        or (recipe.get("omit_fasteners", False) and FASTENER_NAME.search(str(item["name"])))
    )
    translucent = _descendant_refs(
        manifest, {normalized_name(name) for name in recipe.get("translucent_assemblies", [])}
    )
    translucent.update(
        str(item["ref"])
        for item in leaves
        if normalized_name(str(item["name"]))
        in {normalized_name(name) for name in recipe.get("translucent_components", [])}
    )
    translucent -= omitted
    return omitted, translucent, len(leaves)


def bootstrap_recipe(manifest: dict, step: Path) -> dict:
    def historical(path: str) -> dict:
        return yaml.safe_load(
            subprocess.check_output(["git", "show", f"{LEGACY_COMMIT}:{path}"], cwd=REPOSITORY_ROOT)
        )

    old_review = historical("cad/DSG-000095835/reviews/assembly.yaml")
    old_manifest = json.loads(
        subprocess.check_output(
            ["git", "show", f"{LEGACY_COMMIT}:cad/DSG-000095835/manifest.json"],
            cwd=REPOSITORY_ROOT,
        )
    )
    old_by_ref = {item["ref"]: item for item in old_manifest["occurrences"]}
    present = {
        normalized_name(str(item["name"]))
        for item in manifest["occurrences"]
        if not item["is_assembly"]
    }
    reasons: dict[str, set[str]] = defaultdict(set)
    for reason, refs in old_review["omitted_occurrences"].items():
        for ref in refs:
            name = normalized_name(str(old_by_ref[ref]["name"]))
            if name in present:
                reasons[name].add(reason)
    return {
        "schema": "twin-lab-static-review/v1",
        "source_sha256": hashlib.sha256(step.read_bytes()).hexdigest(),
        "baseline": f"{LEGACY_COMMIT}:cad/DSG-000095835/reviews/assembly.yaml",
        "omitted_names": {name: sorted(reasons[name]) for name in sorted(reasons)},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Static STEP review without joints or CoACD")
    parser.add_argument("step", type=Path, help="STEP file to review")
    parser.add_argument("--recipe", type=Path, default=RECIPE)
    parser.add_argument(
        "--bootstrap", action="store_true", help="Create review from the archived omission ledger"
    )
    parser.add_argument(
        "--new-review", action="store_true", help="Start a blank review for a new assembly"
    )
    parser.add_argument("--no-view", action="store_true", help="Export glTF without Meshcat")
    parser.add_argument("--rebuild", action="store_true", help="Re-tessellate the selection")
    parser.add_argument("--carry-review", type=Path, metavar="PREVIOUS_MANIFEST")
    parser.add_argument("--output-review", type=Path)
    parser.add_argument(
        "--decompose", action="store_true", help="Cache CoACD hulls for selected parts and cover"
    )
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    if args.bootstrap and args.new_review:
        parser.error("Choose either --bootstrap or --new-review")

    step = resolve_repo_path(args.step).resolve()
    cache_name = review_cache_name(args.recipe)
    cache = CACHE_ROOT / cache_name
    cache.mkdir(parents=True, exist_ok=True)
    manifest_path = cache / "candidate-manifest.json"
    if not manifest_path.exists() or manifest_path.stat().st_mtime_ns < step.stat().st_mtime_ns:
        write_cad_manifest(step, manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if args.carry_review:
        if args.output_review is None or args.output_review.exists():
            raise ValueError("--carry-review requires an unused --output-review path")
        previous = json.loads(args.carry_review.read_text(encoding="utf-8"))
        original = yaml.safe_load(args.recipe.read_text(encoding="utf-8"))
        carried, added = carry_review(previous, manifest, original, step)
        args.output_review.write_text(yaml.safe_dump(carried, sort_keys=False), encoding="utf-8")
        print(f"Candidate review: {args.output_review}; {len(added)} new component names")
        for name in added:
            print(f"  + {name}")
        return
    if args.bootstrap or args.new_review:
        if args.recipe.exists():
            raise FileExistsError(f"Review already exists: {args.recipe}")
        recipe = (
            bootstrap_recipe(manifest, step)
            if args.bootstrap else {
                "schema": "twin-lab-static-review/v1",
                "source_sha256": hashlib.sha256(step.read_bytes()).hexdigest(),
                "omitted_names": {},
            }
        )
        args.recipe.parent.mkdir(parents=True, exist_ok=True)
        args.recipe.write_text(yaml.safe_dump(recipe, sort_keys=False), encoding="utf-8")
    recipe = yaml.safe_load(args.recipe.read_text(encoding="utf-8"))
    if recipe.get("schema") != "twin-lab-static-review/v1":
        raise ValueError("Unsupported static review recipe")
    if hashlib.sha256(step.read_bytes()).hexdigest() != recipe["source_sha256"]:
        raise ValueError("STEP differs from reviewed source; bootstrap a new review")
    omitted_names = recipe["omitted_names"]
    if not isinstance(omitted_names, dict):
        raise ValueError("omitted_names must map component names to omission reasons")
    present = {
        normalized_name(str(item["name"]))
        for item in manifest["occurrences"]
        if not item["is_assembly"]
    }
    stale = set(omitted_names) - present
    if stale:
        raise ValueError(f"Omitted names absent from STEP: {sorted(stale)}")
    omitted, translucent, total = review_selection(manifest, recipe)
    print(
        f"Static review: {total - len(omitted)} included, {len(omitted)} omitted, "
        f"{len(omitted_names)} matched names"
    )
    if args.decompose:
        sources = prepare_collision_meshes(
            step, manifest, {**recipe, "cache_name": cache_name}
        )
        print(f"Collision sources: {len(sources)} meshes including the hidden cover", flush=True)
        hulls = decompose_sources(
            sources, CACHE_ROOT / "convex-collision" / (
                "DSG-000040389.43841-stage-stack"
                if args.recipe.resolve() == RECIPE.resolve() else cache_name
            ),
            workers=args.workers, progress=True,
        )
        print(f"CoACD: {sum(len(parts) for parts in hulls.values())} parts", flush=True)
        return
    output = cache / "selected.gltf"
    enclosure_output = cache / "enclosure.gltf"
    all_refs = {str(item["ref"]) for item in manifest["occurrences"] if not item["is_assembly"]}
    if (
        args.rebuild
        or not output.exists()
        or output.stat().st_mtime_ns < max(step.stat().st_mtime_ns, args.recipe.stat().st_mtime_ns)
    ):
        write_step_preview(
            step, output, linear_deflection_mm=5.0, angular_deflection_rad=1.2,
            omit_refs=omitted | translucent,
        )
    latest_input = max(step.stat().st_mtime_ns, args.recipe.stat().st_mtime_ns)
    if translucent and (
        args.rebuild or not enclosure_output.exists()
        or enclosure_output.stat().st_mtime_ns < latest_input
    ):
        write_step_preview(
            step, enclosure_output, linear_deflection_mm=5.0, angular_deflection_rad=1.2,
            omit_refs=all_refs - translucent,
        )
        gltf = json.loads(enclosure_output.read_text(encoding="utf-8"))
        gltf["materials"] = [{
            "pbrMetallicRoughness": {
                "baseColorFactor": [0.55, 0.78, 0.83, 0.24], "metallicFactor": 0
            },
            "alphaMode": "BLEND", "doubleSided": True,
        }]
        for mesh in gltf["meshes"]:
            for primitive in mesh["primitives"]:
                primitive["material"] = 0
        enclosure_output.write_text(json.dumps(gltf, separators=(",", ":")), encoding="utf-8")
    print(f"Preview: {output}")
    if not args.no_view:
        view_step_preview(output, enclosure_path=enclosure_output if translucent else None)


if __name__ == "__main__":
    main()