"""Convenience workflow for refreshing the reviewed 43841 stage stack."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path

import yaml

from .constraints_wizard import remap_stage_inventory, write_cad_manifest
from .paths import CACHE_ROOT, REPOSITORY_ROOT
from .stage_cad_viewer import prepare_stage_cad
from .static_review import normalized_name, review_selection

DRAWING_DIR = REPOSITORY_ROOT / "cad" / "DSG-000040389"
SOURCE_STEP = DRAWING_DIR / "source.stp"
MANIFEST = DRAWING_DIR / "manifest.json"
PREVIOUS_MANIFEST = DRAWING_DIR / "manifest.previous.json"
INVENTORY = DRAWING_DIR / "reviews" / "43841-stage-stack.inventory.yaml"
ALIASES = DRAWING_DIR / "reviews" / "43841-stage-stack.aliases.yaml"
STATIC_REVIEW = DRAWING_DIR / "reviews" / "43841-static-review.yaml"


def validate_review_identity(
    inventory: dict, manifest: dict, previous_manifest: dict | None = None,
    ref_map: dict[str, str] | None = None,
) -> list[str]:
    by_ref = {str(item["ref"]): item for item in manifest["occurrences"]}
    old_by_ref = (
        {str(item["ref"]): item for item in previous_manifest["occurrences"]}
        if previous_manifest else {}
    )
    old_ref_for_new = {new: old for old, new in (ref_map or {}).items()}

    def old_identity(ref: str) -> dict | None:
        return old_by_ref.get(old_ref_for_new.get(ref, ref))
    issues: list[str] = []
    root = by_ref.get(str(inventory["subassembly"]["ref"]))
    if root is None or normalized_name(str(root["name"])) != normalized_name(
        str(inventory["subassembly"]["name"])
    ):
        issues.append(
            f"subassembly {inventory['subassembly']['ref']} "
            f"is not {inventory['subassembly']['name']}"
        )
    for spec in inventory.get("static_geometry", []):
        item = by_ref.get(str(spec["ref"]))
        if item is None or normalized_name(str(item["name"])) != normalized_name(
            str(spec["cad_id"])
        ):
            issues.append(f"static geometry {spec['ref']} is not {spec['cad_id']}")
    stage_refs = set()
    for stage in inventory["stage_instances"]:
        ref = str(stage["ref"])
        stage_refs.add(ref)
        item = by_ref.get(ref)
        if item is None or not str(item["name"]).startswith("LIB-"):
            issues.append(f"stage {ref} ({stage['catalog']}) does not identify a library stage")
        old_ref = old_identity(ref)
        if item is not None and old_ref is not None and normalized_name(
            str(item["name"])
        ) != normalized_name(str(old_ref["name"])):
            issues.append(f"stage {ref} changed identity from {old_ref['name']} to {item['name']}")
    for parent_ref, refs in inventory.get("attachment_overrides", {}).get("moving", {}).items():
        parent_ref = str(parent_ref)
        if parent_ref not in stage_refs:
            issues.append(f"moving attachment parent {parent_ref} is not a reviewed stage")
            continue
        for ref in refs:
            item = by_ref.get(str(ref))
            previous = old_identity(str(ref))
            if item is None:
                issues.append(f"attachment {ref} on {parent_ref} is absent")
            elif previous is not None and normalized_name(
                str(item["name"])
            ) != normalized_name(str(previous["name"])):
                issues.append(f"attachment {ref} on {parent_ref} changed identity")
    return issues


def refresh_reviewed_assembly(
    *,
    replacement_step: str | Path | None = None,
    rebuild_viewer_cache: bool = False,
) -> dict[str, Path | list[str]]:
    """Refresh manifest and review data for the reviewed 43841 assembly."""

    replacement = Path(replacement_step).expanduser().resolve() if replacement_step else SOURCE_STEP
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="43841-candidate-", dir=CACHE_ROOT) as directory:
        candidate_dir = Path(directory)
        candidate_manifest = write_cad_manifest(replacement, candidate_dir / "manifest.json")
        candidate_inventory = candidate_dir / "inventory.yaml"
        _, remap_info = remap_stage_inventory(
            INVENTORY,
            previous_manifest_path=MANIFEST,
            new_manifest_path=candidate_manifest,
            output_path=candidate_inventory,
            alias_map_path=ALIASES if ALIASES.exists() else None,
        )
        original = INVENTORY.read_text(encoding="utf-8")
        used_refs = set(re.findall(r"\b[AP]\d{3,}\b", original))
        unresolved = sorted(used_refs.intersection(remap_info["unresolved_refs"]))
        candidate_data = yaml.safe_load(candidate_inventory.read_text(encoding="utf-8"))
        candidate_facts = json.loads(candidate_manifest.read_text(encoding="utf-8"))
        previous_facts = json.loads(MANIFEST.read_text(encoding="utf-8"))
        issues = [f"unresolved occurrence {ref}" for ref in unresolved]
        issues.extend(validate_review_identity(
            candidate_data, candidate_facts, previous_facts, remap_info["ref_map"]
        ))
        if STATIC_REVIEW.exists():
            selection = yaml.safe_load(STATIC_REVIEW.read_text(encoding="utf-8"))
            if selection["source_sha256"] != hashlib.sha256(replacement.read_bytes()).hexdigest():
                issues.append("static selection is pinned to another STEP; carry the review first")
            else:
                try:
                    review_selection(candidate_facts, selection)
                except ValueError as exc:
                    issues.append(f"static selection: {exc}")
        if issues:
            candidate_hash = hashlib.sha256(replacement.read_bytes()).hexdigest()[:16]
            review_dir = CACHE_ROOT / "43841-refresh-candidates" / candidate_hash
            review_dir.mkdir(parents=True, exist_ok=True)
            for source, name in (
                (candidate_manifest, "manifest.json"),
                (candidate_inventory, "inventory.yaml"),
            ):
                destination = review_dir / name
                if not destination.exists():
                    shutil.copy2(source, destination)
            raise ValueError(
                "CAD refresh needs review before replacing files:\n"
                + "\n".join(issues)
                + f"\nCandidate review files: {review_dir}"
            )

        if replacement != SOURCE_STEP:
            shutil.copy2(replacement, SOURCE_STEP)
        if MANIFEST.exists():
            shutil.copy2(MANIFEST, PREVIOUS_MANIFEST)
        candidate_facts["source_step"] = str(SOURCE_STEP)
        MANIFEST.write_text(json.dumps(candidate_facts, indent=2) + "\n", encoding="utf-8")
        _, remap_info = remap_stage_inventory(
            INVENTORY,
            previous_manifest_path=PREVIOUS_MANIFEST,
            new_manifest_path=MANIFEST,
            alias_map_path=ALIASES if ALIASES.exists() else None,
        )
    # An old ref that could not be matched to a new occurrence is left as literal text,
    # so it silently keeps whatever ref number the new revision happens to reassign -
    # stale_refs_still_present is that: which of those old tokens are STILL in the
    # rewritten file, still spelled the same, now meaning something else entirely.
    unresolved_refs = sorted(remap_info["unresolved_refs"])
    rewritten_text = INVENTORY.read_text(encoding="utf-8")
    stale_refs_still_present = [
        ref for ref in unresolved_refs if re.search(rf"\b{re.escape(ref)}\b", rewritten_text)
    ]
    if rebuild_viewer_cache:
        prepare_stage_cad(INVENTORY, rebuild=True)
    return {
        "source_step": SOURCE_STEP,
        "manifest": MANIFEST,
        "previous_manifest": PREVIOUS_MANIFEST,
        "inventory": INVENTORY,
        "aliases": ALIASES,
        "unresolved_refs": unresolved_refs,
        "stale_refs_still_present": stale_refs_still_present,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh the reviewed 43841 stage-stack after replacing its STEP file"
    )
    parser.add_argument(
        "replacement_step",
        nargs="?",
        help="Optional path to a new STEP file to copy into cad/DSG-000040389/source.stp first",
    )
    parser.add_argument(
        "--rebuild-viewer-cache",
        action="store_true",
        help="Rebuild the cached stage viewer scene after remapping",
    )
    args = parser.parse_args()

    results = refresh_reviewed_assembly(
        replacement_step=args.replacement_step,
        rebuild_viewer_cache=args.rebuild_viewer_cache,
    )
    print(f"Reviewed STEP: {results['source_step']}")
    print(f"Previous manifest backup: {results['previous_manifest']}")
    print(f"Refreshed manifest: {results['manifest']}")
    print(f"Remapped inventory: {results['inventory']}")
    if results["aliases"].exists():
        print(f"Alias map used: {results['aliases']}")
    stale_refs = results["stale_refs_still_present"]
    if stale_refs:
        print(
            f"WARNING: {len(stale_refs)} ref(s) in the inventory could not be matched "
            "to the new manifest and were left unchanged - they now point at whatever "
            "the new revision happens to number that same token, NOT the original "
            "occurrence. Review every mention of: " + ", ".join(stale_refs)
        )
    if args.rebuild_viewer_cache:
        print("Viewer cache rebuilt.")


if __name__ == "__main__":
    main()
