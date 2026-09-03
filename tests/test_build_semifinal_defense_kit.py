from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

import tools.build_semifinal_defense_kit as defense_kit

COMMIT = "a" * 40
TREE = "b" * 40


def test_fixed_materials_include_all_six_demo_fallback_frames() -> None:
    expected = {
        f"demo/frames/{name}.png": (
            "demo_fallback_frame",
            f"deliverables/semifinal_rc4_frames/{name}.png",
        )
        for name in (
            "01-public-home",
            "02-command-center",
            "03-case-workbench",
            "04-capa-lineage",
            "05-runs-recheck",
            "06-governance-boundary",
        )
    }

    assert {
        archive_path: defense_kit.FIXED_MATERIALS[archive_path]
        for archive_path in expected
    } == expected


def _snapshot_digest(entries: list[dict[str, object]]) -> str:
    digest = hashlib.sha256()
    for entry in entries:
        digest.update(str(entry["path"]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(entry["sha256"]).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _write_public_snapshot(
    snapshot: Path,
    *,
    payload: bytes = b"public\n",
) -> list[dict[str, object]]:
    snapshot.mkdir(parents=True)
    (snapshot / "LICENSE").write_bytes(payload)
    binary_review_stable = {
        "schema_version": "visiondata-gate.public-binary-review.v1",
        "review_basis": "VISUAL_PIXEL_AND_METADATA_INSPECTION",
        "reviewed_on": "2026-09-02",
        "reviewer_identity_included": False,
        "reviewed_file_count": 0,
        "prohibited_content_checks": [],
        "files": [],
    }
    binary_review = {
        **binary_review_stable,
        "manifest_sha256": hashlib.sha256(
            defense_kit._canonical_json(binary_review_stable)
        ).hexdigest(),
    }
    binary_review_data = defense_kit._canonical_json(binary_review) + b"\n"
    binary_review_path = snapshot / "docs" / "PUBLIC_BINARY_REVIEW.json"
    binary_review_path.parent.mkdir()
    binary_review_path.write_bytes(binary_review_data)
    entries: list[dict[str, object]] = [
        {
            "path": "LICENSE",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size_bytes": len(payload),
        },
        {
            "path": "docs/PUBLIC_BINARY_REVIEW.json",
            "sha256": hashlib.sha256(binary_review_data).hexdigest(),
            "size_bytes": len(binary_review_data),
        },
    ]
    manifest = {
        "schema_version": defense_kit.PUBLIC_MANIFEST_SCHEMA,
        "source_commit_oid": COMMIT,
        "source_tree_oid": TREE,
        "source_worktree_clean": True,
        "source_history_included": False,
        "private_release_evidence_included": False,
        "customer_data_included": False,
        "personal_data_included": False,
        "tracked_source_only": True,
        "file_count": len(entries),
        "snapshot_sha256": _snapshot_digest(entries),
        "files": entries,
    }
    (snapshot / defense_kit.PUBLIC_MANIFEST_NAME).write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    return entries


def _pptx_bytes(
    *,
    extra_members: dict[str, bytes] | None = None,
    external_target: str | None = None,
    content_types: bytes | None = None,
) -> bytes:
    relationships = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    )
    if external_target is not None:
        relationships += (
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
            f'Target="{external_target}" TargetMode="External"/>'
        )
    relationships += "</Relationships>"
    members = {
        "[Content_Types].xml": content_types
        or (
            b'<?xml version="1.0"?><Types '
            b'xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'
        ),
        "_rels/.rels": relationships.encode("utf-8"),
        "ppt/presentation.xml": (
            b'<?xml version="1.0"?><p:presentation '
            b'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>'
        ),
    }
    members.update(extra_members or {})
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _mock_build_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(defense_kit, "FIXED_MATERIALS", {})
    monkeypatch.setattr(defense_kit, "_git_identity", lambda root: (COMMIT, TREE))
    monkeypatch.setattr(defense_kit, "_is_git_ignored", lambda root, path: True)
    monkeypatch.setattr(
        defense_kit,
        "_public_snapshot_materials",
        lambda root, public_snapshot, commit, tree: (
            [defense_kit.Material("source/README.md", "public_source", b"public\n")],
            "c" * 64,
        ),
    )


def test_env_example_is_allowed_only_as_public_source_leaf() -> None:
    defense_kit._reject_sensitive_path(
        "source/web/.env.example",
        allow_env_example=True,
    )
    for rejected in (
        "source/web/.env.example/secret.txt",
        "source/web/.env.example.local",
        "source/web/.ENV.production",
    ):
        with pytest.raises(defense_kit.DefenseKitError) as exc_info:
            defense_kit._reject_sensitive_path(rejected, allow_env_example=True)
        assert exc_info.value.code == "environment_path_rejected"
    with pytest.raises(defense_kit.DefenseKitError):
        defense_kit._reject_sensitive_path("ppt/.env.example")


def test_public_snapshot_outside_root_is_fully_hash_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "private-source"
    root.mkdir()
    snapshot = tmp_path / "official-public-snapshot"
    entries = _write_public_snapshot(snapshot)
    monkeypatch.setattr(
        defense_kit,
        "_validate_public_snapshot_with_checker",
        lambda root, snapshot: None,
    )

    materials, digest = defense_kit._public_snapshot_materials(
        root,
        snapshot,
        commit=COMMIT,
        tree=TREE,
    )

    assert digest == _snapshot_digest(entries)
    assert {material.archive_path for material in materials} == {
        "source/PUBLIC_MIRROR_MANIFEST.json",
        "source/LICENSE",
        "source/docs/PUBLIC_BINARY_REVIEW.json",
    }

    (snapshot / "LICENSE").write_bytes(b"tamper\n")
    with pytest.raises(defense_kit.DefenseKitError) as exc_info:
        defense_kit._public_snapshot_materials(
            root,
            snapshot,
            commit=COMMIT,
            tree=TREE,
        )
    assert exc_info.value.code == "public_snapshot_file_hash_mismatch"


def test_public_snapshot_reuses_repository_privacy_checker(tmp_path: Path) -> None:
    snapshot = tmp_path / "public-snapshot"
    _write_public_snapshot(snapshot)
    project_root = Path(__file__).resolve().parents[1]

    defense_kit._validate_public_snapshot_with_checker(project_root, snapshot)


def test_public_snapshot_materials_fail_closed_when_checker_rejects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "private-source"
    root.mkdir()
    snapshot = tmp_path / "public-snapshot"
    _write_public_snapshot(snapshot)

    def reject_snapshot(root: Path, snapshot: Path) -> None:
        del root, snapshot
        raise defense_kit.DefenseKitError("public_snapshot_validation_failed")

    monkeypatch.setattr(
        defense_kit,
        "_validate_public_snapshot_with_checker",
        reject_snapshot,
    )

    with pytest.raises(defense_kit.DefenseKitError) as exc_info:
        defense_kit._public_snapshot_materials(
            root,
            snapshot,
            commit=COMMIT,
            tree=TREE,
        )
    assert exc_info.value.code == "public_snapshot_validation_failed"


def test_pptx_scans_exact_bytes_and_rejects_active_content() -> None:
    safe = _pptx_bytes(external_target="https://example.com/evidence")
    defense_kit._scan_container(Path("not-present.pptx"), safe)

    active = _pptx_bytes(extra_members={"ppt/embeddings/object.bin": b"payload"})
    with pytest.raises(defense_kit.DefenseKitError) as exc_info:
        defense_kit._scan_container(Path("deck.pptx"), active)
    assert exc_info.value.code == "pptx_active_content_rejected"

    macro_content_type = _pptx_bytes(
        content_types=b"<Types>application/macroEnabled</Types>"
    )
    with pytest.raises(defense_kit.DefenseKitError) as macro_exc:
        defense_kit._scan_container(Path("deck.pptx"), macro_content_type)
    assert macro_exc.value.code == "pptx_active_content_rejected"


def test_pptx_rejects_non_http_external_relationship() -> None:
    unsafe = _pptx_bytes(external_target="file:///factory/private/image.png")
    with pytest.raises(defense_kit.DefenseKitError) as exc_info:
        defense_kit._scan_container(Path("deck.pptx"), unsafe)
    assert exc_info.value.code == "pptx_external_relationship_rejected"


def test_build_is_deterministic_and_publishes_verified_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    _mock_build_inputs(monkeypatch)

    first = defense_kit.build(
        root=root,
        public_snapshot=snapshot,
        output_zip=root / "output" / "first.zip",
        receipt_path=root / "output" / "first.receipt.json",
    )
    second = defense_kit.build(
        root=root,
        public_snapshot=snapshot,
        output_zip=root / "output" / "second.zip",
        receipt_path=root / "output" / "second.receipt.json",
    )

    assert first["status"] == "PASS_LOCAL_RC4_DEFENSE_KIT_INTEGRITY"
    assert first["zip_sha256"] == second["zip_sha256"]
    assert (root / "output" / "first.zip").is_file()
    assert (root / "output" / "first.receipt.json").is_file()


def test_build_failure_leaves_no_final_or_temporary_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    _mock_build_inputs(monkeypatch)
    monkeypatch.setattr(
        defense_kit,
        "_verify_archive",
        lambda path, materials: (_ for _ in ()).throw(
            defense_kit.DefenseKitError("synthetic_archive_failure")
        ),
    )
    output = root / "output" / "kit.zip"
    receipt = root / "output" / "kit.receipt.json"

    with pytest.raises(defense_kit.DefenseKitError) as exc_info:
        defense_kit.build(
            root=root,
            public_snapshot=snapshot,
            output_zip=output,
            receipt_path=receipt,
        )

    assert exc_info.value.code == "synthetic_archive_failure"
    assert not output.exists()
    assert not receipt.exists()
    assert not list(output.parent.glob("*.tmp"))


def test_build_rejects_outputs_inside_public_snapshot(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    snapshot = root / "output" / "snapshot"
    snapshot.mkdir(parents=True)
    with pytest.raises(defense_kit.DefenseKitError) as exc_info:
        defense_kit.build(
            root=root,
            public_snapshot=snapshot,
            output_zip=snapshot / "kit.zip",
            receipt_path=root / "output" / "kit.receipt.json",
        )
    assert exc_info.value.code == "output_snapshot_overlap"


def test_build_rejects_same_zip_and_receipt_path(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    same_path = root / "output" / "bundle.zip"

    with pytest.raises(defense_kit.DefenseKitError) as exc_info:
        defense_kit.build(
            root=root,
            public_snapshot=snapshot,
            output_zip=same_path,
            receipt_path=same_path,
        )

    assert exc_info.value.code == "output_paths_conflict"


def test_main_redacts_unexpected_absolute_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_path = str(tmp_path / "operator-private")

    def fail(**kwargs: object) -> dict[str, object]:
        del kwargs
        raise PermissionError(private_path)

    monkeypatch.setattr(defense_kit, "build", fail)
    result = defense_kit.main(
        [
            "--public-snapshot",
            private_path,
            "--output-zip",
            private_path + ".zip",
            "--receipt",
            private_path + ".json",
        ]
    )

    assert result == 2
    output = capsys.readouterr().out
    assert private_path not in output
    assert json.loads(output)["reason_code"] == "defense_kit_build_failed"
