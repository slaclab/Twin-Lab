import io
import json
import shutil
import tarfile
import xml.etree.ElementTree as ET

import pytest
import yaml

from twin_lab.artifacts import create_bundle, file_sha256, install_bundle


def _runtime_source(root):
    from twin_lab.collision_artifacts import inventory_inputs

    review = root / "review"
    review.mkdir(parents=True)
    inventory = review / "demo.inventory.yaml"
    inventory.write_text(yaml.safe_dump({
        "cad_manifest": "manifest.json", "source_step": "source.stp",
        "stage_catalog": "catalog.yaml",
    }), encoding="utf-8")
    (review / "manifest.json").write_text(json.dumps({
        "occurrences": [{"ref": "P001", "name": "LIB-000001234"}],
    }), encoding="utf-8")
    (review / "source.stp").write_text("CAD revision one", encoding="utf-8")
    (review / "catalog.yaml").write_text("stages: {}\n", encoding="utf-8")
    scene_dir = root / "stage-cad"
    scene_dir.mkdir()
    source = scene_dir / "part.obj"
    source.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8")
    scene = scene_dir / "scene.yaml"
    scene.write_text(yaml.safe_dump({
        "source_fingerprints": inventory_inputs(inventory, "convex")["files"],
        "instances": [{"ref": "A001", "model": "stage", "mesh": str(source)}],
        "motion_stage_meshes": {}, "motion_chains": [], "attachments": [],
    }), encoding="utf-8")
    package = root / "package"
    (package / "meshes").mkdir(parents=True)
    shutil.copy2(source, package / "meshes" / "part.obj")
    (package / "model.sdf").write_text(
        '<sdf version="1.6"><model name="demo"><link name="base"><collision name="part">'
        '<geometry><mesh><uri>meshes/part.obj</uri></mesh></geometry>'
        '</collision></link></model></sdf>', encoding="utf-8",
    )
    (package / "joint_metadata.csv").write_text("joint_name\n", encoding="utf-8")
    decomposition = root / "decomposition"
    (decomposition / "part").mkdir(parents=True)
    shutil.copy2(source, decomposition / "part" / "hull.obj")
    (decomposition / "part" / "manifest.json").write_text(json.dumps({
        "source": str(source), "parts": [{"part_ref": "P001", "hulls": ["hull.obj"]}],
    }), encoding="utf-8")
    return inventory, package, scene, decomposition


def test_bundle_installs_portably_and_reuses_verified_files_offline(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "mesh.obj").write_text("v 0 0 0\n", encoding="utf-8")
    archive = tmp_path / "geometry.tar.gz"
    reference = create_bundle(source, archive, inputs={"cad": "reviewed-sha256"})
    reference = json.loads(json.dumps(reference))
    installed = install_bundle(reference, tmp_path / "store")
    assert (installed / "mesh.obj").read_bytes() == (source / "mesh.obj").read_bytes()
    archive.unlink()
    assert install_bundle(reference, tmp_path / "store", offline=True) == installed


def test_corrupt_installed_bundle_fails_without_overwriting_other_revisions(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "mesh.obj").write_text("original", encoding="utf-8")
    reference = create_bundle(source, tmp_path / "geometry.tar.gz", inputs={})
    installed = install_bundle(reference, tmp_path / "store")
    (installed / "mesh.obj").chmod(0o644)
    (installed / "mesh.obj").write_text("corrupted", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        install_bundle(reference, tmp_path / "store", offline=True)
    assert (installed / "mesh.obj").read_text(encoding="utf-8") == "corrupted"


def test_refiner_resolves_portable_manifest_sources(tmp_path):
    from twin_lab.clearance_refine import _index_parts

    meshes = tmp_path / "tessellations"
    meshes.mkdir()
    source = meshes / "stage.obj"
    source.write_text("v 0 0 0\n", encoding="utf-8")
    parts = tmp_path / "decomposition" / "stage"
    parts.mkdir(parents=True)
    (parts / "manifest.json").write_text(json.dumps({
        "source": "../../tessellations/stage.obj",
        "parts": [{"part_ref": "P001", "hulls": ["hull.obj"]}],
    }), encoding="utf-8")
    assert _index_parts(tmp_path / "decomposition")["P001"].source == source


def test_collision_startup_without_reference_never_builds(tmp_path, monkeypatch):
    import sys

    from twin_lab import collision_viewer, stage_cad_viewer

    inventory = tmp_path / "new.inventory.yaml"
    inventory.write_text("schema: slac-stage-inventory/v1\n", encoding="utf-8")

    def forbidden(*args, **kwargs):
        pytest.fail("Viewer startup must not build CAD")

    monkeypatch.setattr(stage_cad_viewer, "prepare_stage_cad", forbidden)
    monkeypatch.setattr(sys, "argv", ["slac-collision", str(inventory)])
    with pytest.raises(SystemExit) as error:
        collision_viewer.main()
    assert error.value.code == 2


def test_collision_startup_uses_bundle_and_explicit_port(tmp_path, monkeypatch):
    import sys

    from twin_lab import collision_artifacts, collision_viewer

    (tmp_path / "runtime.json").write_text(
        json.dumps({"collision_mode": "convex"}), encoding="utf-8"
    )
    (tmp_path / "decomposition").mkdir()
    received = {}

    def resolve(inventory, **kwargs):
        assert kwargs["offline"] is True
        return tmp_path

    def run(package, **kwargs):
        received.update(package=package, **kwargs)

    monkeypatch.setattr(collision_artifacts, "resolve_runtime", resolve)
    monkeypatch.setattr(collision_viewer, "run_collision_viewer", run)
    monkeypatch.setattr(sys, "argv", [
        "slac-collision", "demo.inventory.yaml", "--offline", "--port", "7001",
    ])
    collision_viewer.main()
    assert received["package"] == tmp_path / "package"
    assert received["port"] == 7001
    assert received["beam_cache_dir"] == tmp_path / "tessellations"
    assert received["decomposition_dir"] == tmp_path / "decomposition"


def test_complete_runtime_is_portable_and_metadata_stays_in_bundle(tmp_path):
    from twin_lab.clearance_refine import _index_parts
    from twin_lab.collision import read_part_labels
    from twin_lab.collision_artifacts import capture_bundle, resolve_runtime, write_reference

    inventory, package, scene, decomposition = _runtime_source(tmp_path / "author")
    reference = capture_bundle(
        inventory, package, scene, decomposition, tmp_path / "runtime.tar.gz",
    )
    clone = tmp_path / "clone"
    shutil.copytree(inventory.parent, clone)
    selected = clone / "demo.artifacts.json"
    write_reference(selected, reference)
    shutil.rmtree(tmp_path / "author")
    root = resolve_runtime(
        clone / inventory.name, reference=selected, store=tmp_path / "installed",
    )
    assert read_part_labels(root / "review" / "inventory.yaml") == {"P001": "LIB-000001234"}
    assert _index_parts(root / "decomposition")["P001"].source.is_file()
    assert str(tmp_path / "author") not in (
        root / "decomposition" / "part" / "manifest.json"
    ).read_text(encoding="utf-8")


def test_changed_inventory_requires_intentional_new_artifacts(tmp_path):
    from twin_lab.collision_artifacts import capture_bundle, resolve_runtime, write_reference

    inventory, package, scene, decomposition = _runtime_source(tmp_path / "author")
    reference = capture_bundle(
        inventory, package, scene, decomposition, tmp_path / "runtime.tar.gz",
    )
    selected = tmp_path / "reference.json"
    write_reference(selected, reference)
    inventory.write_text(inventory.read_text(encoding="utf-8") + "home: 180\n", encoding="utf-8")
    with pytest.raises(ValueError, match="differs from the pinned"):
        resolve_runtime(inventory, reference=selected, store=tmp_path / "installed")
    assert not (tmp_path / "installed").exists()


def test_capture_rejects_stale_scene_fingerprints(tmp_path):
    from twin_lab.collision_artifacts import capture_bundle

    inventory, package, scene, decomposition = _runtime_source(tmp_path / "author")
    inventory.write_text(inventory.read_text(encoding="utf-8") + "home: 180\n", encoding="utf-8")
    with pytest.raises(ValueError, match="fingerprints"):
        capture_bundle(inventory, package, scene, decomposition, tmp_path / "runtime.tar.gz")
    assert not (tmp_path / "runtime.tar.gz").exists()


def test_failed_download_leaves_no_installed_revision(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "mesh.obj").write_text("original", encoding="utf-8")
    archive = tmp_path / "geometry.tar.gz"
    reference = create_bundle(source, archive, inputs={})
    archive.write_bytes(b"corrupt download")
    with pytest.raises(ValueError, match="checksum"):
        install_bundle(reference, tmp_path / "store")
    assert list((tmp_path / "store").iterdir()) == []


def test_revisions_have_independent_directories_and_corruption_is_isolated(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    mesh = source / "mesh.obj"
    mesh.write_text("original", encoding="utf-8")
    old = create_bundle(source, tmp_path / "old.tar.gz", inputs={})
    old_root = install_bundle(old, tmp_path / "store")
    mesh.write_text("new CAD", encoding="utf-8")
    new = create_bundle(source, tmp_path / "new.tar.gz", inputs={})
    new_root = install_bundle(new, tmp_path / "store")
    (new_root / "mesh.obj").chmod(0o644)
    (new_root / "mesh.obj").write_text("broken", encoding="utf-8")
    assert old_root != new_root
    assert install_bundle(old, tmp_path / "store", offline=True) == old_root
    assert (old_root / "mesh.obj").read_text(encoding="utf-8") == "original"


def test_bundle_archive_is_reproducible_and_cannot_be_overwritten(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "mesh.obj").write_text("original", encoding="utf-8")
    first = create_bundle(source, tmp_path / "one.tar.gz", inputs={})
    second = create_bundle(source, tmp_path / "two.tar.gz", inputs={})
    assert first["bundle_id"] == second["bundle_id"]
    assert first["sha256"] == second["sha256"]
    with pytest.raises(FileExistsError):
        create_bundle(source, tmp_path / "one.tar.gz", inputs={})


@pytest.mark.parametrize("name,kind", [
    ("../escape.obj", tarfile.REGTYPE),
    ("/escape.obj", tarfile.REGTYPE),
    ("mesh.obj", tarfile.SYMTYPE),
    ("mesh.obj", tarfile.LNKTYPE),
])
def test_unsafe_archive_members_are_rejected_without_installing(tmp_path, name, kind):
    source = tmp_path / "source"
    source.mkdir()
    (source / "mesh.obj").write_text("original", encoding="utf-8")
    archive = tmp_path / "geometry.tar.gz"
    reference = create_bundle(source, archive, inputs={})
    with tarfile.open(archive, "r:gz") as bundle:
        manifest_bytes = bundle.extractfile("bundle.json").read()
    with tarfile.open(archive, "w:gz") as bundle:
        manifest = tarfile.TarInfo("bundle.json")
        manifest.size = len(manifest_bytes)
        bundle.addfile(manifest, io.BytesIO(manifest_bytes))
        member = tarfile.TarInfo(name)
        member.type = kind
        member.linkname = "../escape.obj" if kind != tarfile.REGTYPE else ""
        bundle.addfile(member)
    reference["sha256"] = file_sha256(archive)
    with pytest.raises(ValueError, match="Unsafe"):
        install_bundle(reference, tmp_path / "store")
    assert not (tmp_path / "escape.obj").exists()
    assert list((tmp_path / "store").iterdir()) == []


def test_published_geometry_is_installed_read_only(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "mesh.obj").write_text("original", encoding="utf-8")
    reference = create_bundle(source, tmp_path / "geometry.tar.gz", inputs={})
    installed = install_bundle(reference, tmp_path / "store")
    assert installed.stat().st_mode & 0o222 == 0
    assert (installed / "mesh.obj").stat().st_mode & 0o222 == 0


def test_publish_never_clobbers_release_assets_or_updates_reference_on_failure(
    tmp_path, monkeypatch,
):
    import subprocess
    import sys

    from twin_lab import collision_artifacts

    inventory, package, scene, decomposition = _runtime_source(tmp_path / "author")
    archive = tmp_path / "runtime.tar.gz"
    reference = collision_artifacts.capture_bundle(
        inventory, package, scene, decomposition, archive,
    )
    selected = tmp_path / "reference.json"
    collision_artifacts.write_reference(selected, reference)
    original = selected.read_bytes()

    def publish(command, **kwargs):
        assert "--clobber" not in command
        assert command[:3] == ["gh", "release", "upload"]
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(collision_artifacts.subprocess, "run", publish)
    monkeypatch.setattr(sys, "argv", [
        "slac-artifacts", "publish", str(inventory), "--reference", str(selected),
        "--archive", str(archive), "--repo", "owner/repo", "--tag", "geometry-v1",
    ])
    with pytest.raises(SystemExit) as error:
        collision_artifacts.main()
    assert error.value.code == 2
    assert selected.read_bytes() == original


def test_capture_accepts_legacy_drake_xml_prefixes(tmp_path):
    from twin_lab.collision_artifacts import capture_bundle

    inventory, package, scene, decomposition = _runtime_source(tmp_path / "author")
    model = package / "model.sdf"
    tree = ET.parse(model)
    ET.SubElement(tree.find(".//mesh"), "drake:declare_convex")
    tree.write(model)
    reference = capture_bundle(
        inventory, package, scene, decomposition, tmp_path / "runtime.tar.gz",
    )
    assert reference["bundle_id"]


def test_capture_does_not_include_unused_stale_decompositions(tmp_path):
    from twin_lab.collision_artifacts import capture_bundle

    inventory, package, scene, decomposition = _runtime_source(tmp_path / "author")
    obsolete = decomposition / "obsolete"
    obsolete.mkdir()
    (obsolete / "manifest.json").write_text(json.dumps({
        "source": str(tmp_path / "deleted-source.obj"), "source_sha256": "stale", "parts": [],
    }), encoding="utf-8")
    reference = capture_bundle(
        inventory, package, scene, decomposition, tmp_path / "runtime.tar.gz",
    )
    root = install_bundle(reference, tmp_path / "store")
    assert not (root / "decomposition" / "obsolete").exists()


def test_published_review_accepts_matching_git_lfs_pointer_without_step_download(tmp_path):
    from twin_lab.collision_artifacts import capture_bundle, resolve_runtime, write_reference

    inventory, package, scene, decomposition = _runtime_source(tmp_path / "author")
    reference = capture_bundle(
        inventory, package, scene, decomposition, tmp_path / "runtime.tar.gz",
    )
    selected = tmp_path / "reference.json"
    write_reference(selected, reference)
    source = inventory.parent / "source.stp"
    digest, size = file_sha256(source), source.stat().st_size
    source.write_text(
        f"version https://git-lfs.github.com/spec/v1\noid sha256:{digest}\nsize {size}\n",
        encoding="utf-8",
    )
    root = resolve_runtime(inventory, reference=selected, store=tmp_path / "installed")
    assert (root / "package" / "model.sdf").is_file()


def test_failed_explicit_build_keeps_installed_bundles_and_references(tmp_path, monkeypatch):
    from twin_lab import collision_artifacts, stage_cad_viewer

    inventory, package, scene, decomposition = _runtime_source(tmp_path / "author")
    reference = collision_artifacts.capture_bundle(
        inventory, package, scene, decomposition, tmp_path / "runtime.tar.gz",
    )
    store = tmp_path / "work" / "artifacts"
    installed = install_bundle(reference, store)
    selected = tmp_path / "reference.json"
    collision_artifacts.write_reference(selected, reference)
    original_reference = selected.read_bytes()
    monkeypatch.setattr(collision_artifacts, "CACHE_ROOT", store.parent)

    def failed_build(inventory, *, rebuild, cache_root):
        assert rebuild is True
        assert cache_root != store.parent
        assert cache_root.parent == store.parent
        raise RuntimeError("simulated tessellation failure")

    monkeypatch.setattr(stage_cad_viewer, "prepare_stage_cad", failed_build)
    with pytest.raises(RuntimeError, match="simulated tessellation failure"):
        collision_artifacts.build_bundle(inventory, tmp_path / "new.tar.gz")
    assert selected.read_bytes() == original_reference
    assert install_bundle(reference, store, offline=True) == installed
    assert not (tmp_path / "new.tar.gz").exists()


def test_touching_review_files_does_not_invalidate_saved_geometry(tmp_path):
    import os

    from twin_lab.collision_artifacts import capture_bundle, resolve_runtime, write_reference

    inventory, package, scene, decomposition = _runtime_source(tmp_path / "author")
    reference = capture_bundle(
        inventory, package, scene, decomposition, tmp_path / "runtime.tar.gz",
    )
    selected = tmp_path / "reference.json"
    write_reference(selected, reference)
    for path in inventory.parent.iterdir():
        os.utime(path, (0, 0))
    assert resolve_runtime(inventory, reference=selected, store=tmp_path / "installed").is_dir()


def test_explicit_build_compiles_portable_sdf_in_isolated_workspace(tmp_path, monkeypatch):
    from twin_lab import collision_artifacts, sdf_compiler, stage_cad_viewer

    inventory, _, _, _ = _runtime_source(tmp_path / "author")
    work = tmp_path / "working-cache"
    monkeypatch.setattr(collision_artifacts, "CACHE_ROOT", work)

    def prepare(selected, *, rebuild, cache_root):
        assert selected == inventory
        assert rebuild is True
        assert cache_root.is_relative_to(work)
        directory = cache_root / "stage-cad" / "test"
        directory.mkdir(parents=True)
        mesh = directory / "part.obj"
        mesh.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8")
        scene = directory / "scene.yaml"
        scene.write_text(yaml.safe_dump({
            "schema": "slac-stage-cad-scene/v8",
            "source_fingerprints": collision_artifacts.inventory_inputs(inventory, "hull")["files"],
            "instances": [{"ref": "A001", "model": "stage", "mesh": str(mesh)}],
            "motion_stage_meshes": {}, "motion_chains": [], "attachments": [],
        }), encoding="utf-8")
        return scene

    def forbidden(*args, **kwargs):
        pytest.fail("Hull-mode integration fixture must not run CoACD")

    monkeypatch.setattr(stage_cad_viewer, "prepare_stage_cad", prepare)
    monkeypatch.setattr(sdf_compiler, "decompose_sources", forbidden)
    reference = collision_artifacts.build_bundle(
        inventory, tmp_path / "built.tar.gz", collision_mode="hull",
    )
    assert list(work.iterdir()) == []
    installed = install_bundle(reference, tmp_path / "installed")
    collision_artifacts.validate_runtime(installed)
    assert len(list((installed / "package").glob("*.sdf"))) == 2
    assert reference["inputs"]["collision_mode"] == "hull"