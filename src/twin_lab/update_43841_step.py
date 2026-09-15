"""Convenience workflow for refreshing the reviewed 43841 stage stack."""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

from .constraints_wizard import remap_stage_inventory, write_cad_manifest
from .paths import REPOSITORY_ROOT
from .stage_cad_viewer import prepare_stage_cad

DRAWING_DIR = REPOSITORY_ROOT / "cad" / "DSG-000040389"
SOURCE_STEP = DRAWING_DIR / "source.stp"
MANIFEST = DRAWING_DIR / "manifest.json"
PREVIOUS_MANIFEST = DRAWING_DIR / "manifest.previous.json"
INVENTORY = DRAWING_DIR / "reviews" / "43841-stage-stack.inventory.yaml"
ALIASES = DRAWING_DIR / "reviews" / "43841-stage-stack.aliases.yaml"


def refresh_reviewed_assembly(
    *,
    replacement_step: str | Path | None = None,
    rebuild_viewer_cache: bool = False,
) -> dict[str, Path | list[str]]:
    """Refresh manifest and review data for the reviewed 43841 assembly."""

    if replacement_step is not None:
        replacement = Path(replacement_step).expanduser().resolve()
        if replacement == SOURCE_STEP:
            replacement = None
        else:
            shutil.copy2(replacement, SOURCE_STEP)

    if MANIFEST.exists():
        shutil.copy2(MANIFEST, PREVIOUS_MANIFEST)
    write_cad_manifest(SOURCE_STEP, MANIFEST)
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
