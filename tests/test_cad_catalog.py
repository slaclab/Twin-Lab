import json

import pytest
import yaml

from twin_lab.cad_catalog import ingest_step, list_revisions, read_revision
from twin_lab.collision_artifacts import inventory_inputs

from .test_artifacts import _runtime_source


def test_ingest_preserves_original_and_catalogs_revision_without_replacing_old(tmp_path):
    root = tmp_path / "repo"
    source = tmp_path / "export.stp"
    source.write_text("first STEP revision", encoding="utf-8")
    first = ingest_step(source, "DSG-000040389", root=root)
    source.write_text("second STEP revision", encoding="utf-8")
    second = ingest_step(source, "DSG-000040389", root=root, parent=first["revision_id"])
    assert first["revision_id"] != second["revision_id"]
    assert (root / first["step"]["path"]).read_text() == "first STEP revision"
    assert (root / second["step"]["path"]).read_text() == "second STEP revision"
    assert first["assembly"] == "DSG-000040389"
    assert first["ingested_at"].endswith("Z")
    assert first["status"] == "awaiting_review"
    assert second["parent_revision"] == first["revision_id"]
    assert len(list_revisions(root=root)) == 2
    assert read_revision(first["revision_id"], root=root) == first


def test_reingest_is_idempotent_and_keeps_first_registration_time(tmp_path):
    source = tmp_path / "export.stp"
    source.write_text("same STEP", encoding="utf-8")
    first = ingest_step(source, "assembly", root=tmp_path / "repo")
    second = ingest_step(source, "assembly", root=tmp_path / "repo")
    assert first == second


def test_catalog_detects_damage_to_saved_step(tmp_path):
    root = tmp_path / "repo"
    source = tmp_path / "export.stp"
    source.write_text("original STEP", encoding="utf-8")
    record = ingest_step(source, "assembly", root=root)
    saved = root / record["step"]["path"]
    saved.chmod(0o644)
    saved.write_text("damaged STEP", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        read_revision(record["revision_id"], root=root)


def test_catalog_binds_step_to_bundle_and_launches_without_original_review(tmp_path):
    import shutil

    from twin_lab.cad_catalog import register_bundle, resolve_revision_runtime
    from twin_lab.collision_artifacts import capture_bundle, write_reference

    root = tmp_path / "repo"
    inventory, package, scene, decomposition = _runtime_source(root / "author")
    reference = capture_bundle(
        inventory, package, scene, decomposition, tmp_path / "bundle.tar.gz",
    )
    selected = tmp_path / "reference.json"
    write_reference(selected, reference)
    record = register_bundle(
        inventory, selected, root=root, assembly="assembly", store=tmp_path / "store",
    )
    assert record["status"] == "cached"
    assert record["uploaded_at"] is None
    assert record["timestamp_basis"] == "registered_existing"
    assert record["bundles"][0]["reference"]["cad"]["revision_id"] == record["revision_id"]
    shutil.rmtree(root / "author")
    installed = resolve_revision_runtime(
        record["revision_id"], root=root, store=tmp_path / "store", offline=True,
    )
    assert (installed / "package" / "model.sdf").is_file()


def test_catalog_rejects_bundle_step_binding_tampering(tmp_path):
    from twin_lab.cad_catalog import register_bundle
    from twin_lab.collision_artifacts import capture_bundle, write_reference

    root = tmp_path / "repo"
    inventory, package, scene, decomposition = _runtime_source(root / "author")
    descriptor = capture_bundle(
        inventory, package, scene, decomposition, tmp_path / "bundle.tar.gz",
    )
    selected = tmp_path / "reference.json"
    write_reference(selected, descriptor)
    record = register_bundle(
        inventory, selected, root=root, assembly="assembly", store=tmp_path / "store",
    )
    binding_path = root / record["bundles"][0]["catalog_path"]
    binding = json.loads(binding_path.read_text())
    binding["reference"]["inputs"]["files"]["source_step"] = "0" * 64
    binding_path.write_text(json.dumps(binding))
    with pytest.raises(ValueError, match="STEP binding"):
        read_revision(record["revision_id"], root=root)


def test_new_bundles_carry_catalog_metadata_inside_verified_archive(tmp_path):
    from twin_lab.artifacts import install_bundle
    from twin_lab.cad_catalog import revision_metadata
    from twin_lab.collision_artifacts import capture_bundle

    root = tmp_path / "repo"
    inventory, package, scene, decomposition = _runtime_source(root / "author")
    record = ingest_step(inventory.parent / "source.stp", "assembly", root=root)
    metadata = revision_metadata(record)
    descriptor = capture_bundle(
        inventory, package, scene, decomposition, tmp_path / "bundle.tar.gz",
        cad_metadata=metadata,
    )
    installed = install_bundle(descriptor, tmp_path / "store")
    manifest = json.loads((installed / "bundle.json").read_text())
    assert manifest["metadata"]["cad"] == metadata
    assert manifest["metadata"]["cad"]["step"]["sha256"] == (
        descriptor["inputs"]["files"]["source_step"]
    )


def test_two_complete_revisions_keep_correct_step_bundle_pairs(tmp_path):
    from twin_lab.cad_catalog import register_bundle, resolve_revision_runtime
    from twin_lab.collision_artifacts import capture_bundle, write_reference

    root = tmp_path / "repo"
    records = []
    for label in ("old", "new"):
        inventory, package, scene, decomposition = _runtime_source(root / label)
        step = inventory.parent / "source.stp"
        if label == "new":
            step.write_text("new CAD revision", encoding="utf-8")
            content = yaml.safe_load(scene.read_text())
            content["source_fingerprints"] = inventory_inputs(inventory, "convex")["files"]
            scene.write_text(yaml.safe_dump(content))
        descriptor = capture_bundle(
            inventory, package, scene, decomposition, tmp_path / f"{label}.tar.gz",
        )
        selected = tmp_path / f"{label}.json"
        write_reference(selected, descriptor)
        records.append(register_bundle(
            inventory, selected, root=root, assembly="assembly", store=tmp_path / "store",
        ))
    assert records[0]["step"]["sha256"] != records[1]["step"]["sha256"]
    assert records[0]["bundles"][0]["bundle_id"] != records[1]["bundles"][0]["bundle_id"]
    for record in records:
        assert resolve_revision_runtime(
            record["revision_id"], root=root, store=tmp_path / "store", offline=True,
        ).is_dir()


def test_catalog_keeps_healthy_revisions_discoverable_when_one_is_damaged(tmp_path):
    root = tmp_path / "repo"
    source = tmp_path / "export.stp"
    source.write_text("first STEP")
    first = ingest_step(source, "assembly", root=root)
    source.write_text("second STEP")
    second = ingest_step(source, "assembly", root=root)
    saved = root / first["step"]["path"]
    saved.chmod(0o644)
    saved.write_text("damaged")
    records = {record["revision_id"]: record for record in list_revisions(root=root)}
    assert records[first["revision_id"]]["status"] == "invalid"
    assert "checksum" in records[first["revision_id"]]["error"]
    assert records[second["revision_id"]]["status"] == "awaiting_review"


def test_capture_rejects_metadata_for_another_step(tmp_path):
    from twin_lab.cad_catalog import revision_metadata
    from twin_lab.collision_artifacts import capture_bundle

    root = tmp_path / "repo"
    inventory, package, scene, decomposition = _runtime_source(root / "author")
    record = ingest_step(inventory.parent / "source.stp", "assembly", root=root)
    metadata = revision_metadata(record)
    metadata["step"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="different STEP"):
        capture_bundle(
            inventory, package, scene, decomposition, tmp_path / "bundle.tar.gz",
            cad_metadata=metadata,
        )


def test_short_selectors_resolve_uniquely_and_preserve_full_parent_ids(tmp_path):
    root = tmp_path / "repo"
    source = tmp_path / "export.stp"
    source.write_text("old STEP")
    old = ingest_step(source, "assembly", root=root)
    assert read_revision(old["selector"], root=root)["revision_id"] == old["revision_id"]
    source.write_text("new STEP")
    new = ingest_step(source, "assembly", root=root, parent=old["selector"])
    assert new["parent_revision"] == old["revision_id"]


def test_catalog_discovers_saved_cad_from_matching_lfs_pointer(tmp_path):
    root = tmp_path / "repo"
    source = tmp_path / "export.stp"
    source.write_text("original STEP")
    record = ingest_step(source, "assembly", root=root)
    saved = root / record["step"]["path"]
    saved.chmod(0o644)
    saved.write_text(
        "version https://git-lfs.github.com/spec/v1\n"
        f"oid sha256:{record['step']['sha256']}\nsize {record['step']['size_bytes']}\n"
    )
    assert read_revision(record["selector"], root=root)["revision_id"] == record["revision_id"]


def test_capture_command_automatically_catalogs_and_embeds_metadata(tmp_path, monkeypatch):
    import sys

    from twin_lab import collision_artifacts, sdf_compiler

    root = tmp_path / "repo"
    inventory, package, scene, decomposition = _runtime_source(root / "author")
    cache = root / ".cache" / "twin_lab"
    monkeypatch.setattr(collision_artifacts, "REPOSITORY_ROOT", root)
    monkeypatch.setattr(collision_artifacts, "CACHE_ROOT", cache)
    monkeypatch.setattr(sdf_compiler, "package_is_current", lambda *args, **kwargs: True)
    selected = tmp_path / "selected.json"
    monkeypatch.setattr(sys, "argv", [
        "slac-artifacts", "capture", str(inventory), "--archive", str(tmp_path / "bundle.tar.gz"),
        "--reference", str(selected), "--scene", str(scene), "--package-dir", str(package),
        "--decomposition-dir", str(decomposition),
    ])
    collision_artifacts.main()
    records = list_revisions(root=root)
    assert len(records) == 1
    assert records[0]["status"] == "cached"
    descriptor = json.loads(selected.read_text())
    assert descriptor["cad"]["revision_id"] == records[0]["revision_id"]
    manifest_path = cache / "artifacts" / descriptor["bundle_id"] / "bundle.json"
    manifest = json.loads(manifest_path.read_text())
    assert manifest["metadata"]["cad"] == descriptor["cad"]


def test_viewer_launches_catalog_revision_without_inventory_discovery(tmp_path, monkeypatch):
    import sys

    from twin_lab import cad_catalog, collision_viewer

    (tmp_path / "runtime.json").write_text(json.dumps({"collision_mode": "convex"}))
    received = {}

    def resolve(revision, **kwargs):
        assert revision == "assembly-12345678"
        assert kwargs["offline"] is True
        return tmp_path

    def run(package, **kwargs):
        received.update(package=package, **kwargs)

    monkeypatch.setattr(cad_catalog, "resolve_revision_runtime", resolve)
    monkeypatch.setattr(collision_viewer, "run_collision_viewer", run)
    monkeypatch.setattr(sys, "argv", [
        "slac-collision", "--revision", "assembly-12345678", "--offline", "--port", "7002",
    ])
    collision_viewer.main()
    assert received["package"] == tmp_path / "package"
    assert received["port"] == 7002