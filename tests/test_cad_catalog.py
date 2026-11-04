import json

import pytest

from twin_lab.cad_catalog import ingest_step, list_revisions, read_revision


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