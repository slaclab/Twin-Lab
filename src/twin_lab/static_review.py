"""Review a name-filtered STEP assembly without motion or collision compilation."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path

import yaml

from .constraints_wizard import view_step_preview, write_cad_manifest, write_step_preview
from .paths import CACHE_ROOT, REPOSITORY_ROOT, resolve_repo_path

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


def select_leaves(manifest: dict, omitted_names: dict[str, list[str]]) -> tuple[set[str], int]:
    leaves = [item for item in manifest["occurrences"] if not item["is_assembly"]]
    names = set(omitted_names)
    omitted = {str(item["ref"]) for item in leaves if normalized_name(str(item["name"])) in names}
    return omitted, len(leaves)


def review_selection(manifest: dict, recipe: dict) -> tuple[set[str], set[str], int]:
    occurrences = manifest["occurrences"]
    leaves = [item for item in occurrences if not item["is_assembly"]]
    assemblies = [item for item in occurrences if item["is_assembly"]]
    actual_names = {normalized_name(str(item["name"])) for item in occurrences}
    requested = {
        normalized_name(name)
        for key in ("omitted_assemblies", "omitted_components", "translucent_assemblies")
        for name in recipe.get(key, [])
    }
    missing = requested - actual_names
    if missing:
        raise ValueError(f"Reviewed component names absent from STEP: {sorted(missing)}")

    def descendants(names: set[str]) -> set[str]:
        roots = [
            str(item["id"])
            for item in assemblies
            if normalized_name(str(item["name"])) in names
        ]
        return {
            str(item["ref"])
            for item in leaves
            if any(str(item["id"]).startswith(f"{root}/") for root in roots)
        }

    omitted = descendants({normalized_name(name) for name in recipe.get("omitted_assemblies", [])})
    omitted.update(
        str(item["ref"])
        for item in leaves
        if normalized_name(str(item["name"])) in recipe["omitted_names"]
        or normalized_name(str(item["name"]))
        in {normalized_name(name) for name in recipe.get("omitted_components", [])}
        or (recipe.get("omit_fasteners", False) and FASTENER_NAME.search(str(item["name"])))
    )
    translucent = descendants(
        {normalized_name(name) for name in recipe.get("translucent_assemblies", [])}
    ) - omitted
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
    parser.add_argument("--no-view", action="store_true", help="Export glTF without Meshcat")
    parser.add_argument("--rebuild", action="store_true", help="Re-tessellate the selection")
    args = parser.parse_args()

    step = resolve_repo_path(args.step).resolve()
    cache = CACHE_ROOT / "43841-static-review"
    cache.mkdir(parents=True, exist_ok=True)
    manifest_path = cache / "candidate-manifest.json"
    if not manifest_path.exists() or manifest_path.stat().st_mtime_ns < step.stat().st_mtime_ns:
        write_cad_manifest(step, manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if args.bootstrap:
        if args.recipe.exists():
            raise FileExistsError(f"Review already exists: {args.recipe}")
        recipe = bootstrap_recipe(manifest, step)
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