from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
import tools.check_public_pages as public_pages_checker
import tools.check_public_repository as public_repository_checker
import tools.export_public_repository as public_exporter
from tools.check_public_pages import (
    PUBLIC_MANIFEST,
    PublicPagesValidationError,
    _scan_runtime_surfaces,
    _scan_text,
    validate_dist,
    validate_manifest,
)
from tools.check_public_repository import (
    HISTORY_PATH_UNAVAILABLE,
    PUBLIC_BINARY_REVIEW_PATH,
    PublicRepositoryValidationError,
    _binary_review_violations,
    _content_violations,
    _historical_blob_violations,
    _history_environment_violations,
    _history_inventory,
    _history_objects,
    _path_violations,
    _report_path_and_findings,
    _revision_metadata_violations,
    _revision_metadata_objects,
    _scan_commit_identities,
    _scan_history_blobs,
    _scan_ref_names,
    validate_snapshot,
)
from tools.export_public_repository import (
    PUBLIC_CI_TEMPLATE,
    PUBLIC_CI_WORKFLOW,
    PUBLIC_PAGES_TEMPLATE,
    PUBLIC_PAGES_WORKFLOW,
    _selected,
    export,
)


def test_public_export_requires_a_clean_source_worktree(monkeypatch) -> None:
    monkeypatch.setattr(
        public_exporter,
        "_git_text",
        lambda *args: " M docs/private.md" if args[0] == "status" else "a" * 40,
    )
    with pytest.raises(
        public_exporter.PublicExportError,
        match="source worktree must be clean",
    ):
        public_exporter._source_identity()


def test_public_export_is_allowlist_based_and_excludes_private_delivery_surfaces() -> (
    None
):
    assert _selected("CONTRIBUTING.md")
    assert _selected("SECURITY.md")
    assert _selected("CODE_OF_CONDUCT.md")
    assert _selected(".streamlit/config.toml")
    assert _selected("src/visiondata_gate/api.py")
    assert _selected("web/public/public-replay.v1.json")
    assert _selected("sample_data/clear/clean-val-gear.png")
    assert _selected("docs/PUBLICATION_BOUNDARY.md")
    assert _selected("docs/CARGO_LICENSES.locked.json")
    for semifinal_document in (
        "docs/GOAI_SEMIFINAL_GUIDE_20260902.md",
        "docs/DEMO_60S_SCRIPT_SEMIFINAL.md",
        "docs/DEFENSE_3MIN_SCRIPT_SEMIFINAL.md",
        "docs/DEFENSE_QA_SEMIFINAL.md",
        "docs/SEMIFINAL_DEFENSE_RUNBOOK_20260902.md",
    ):
        assert _selected(semifinal_document)
    assert _selected(PUBLIC_BINARY_REVIEW_PATH)
    assert _selected(PUBLIC_PAGES_TEMPLATE)
    assert _selected(PUBLIC_CI_TEMPLATE)
    assert not _selected(PUBLIC_PAGES_WORKFLOW)
    assert not _selected(PUBLIC_CI_WORKFLOW)
    assert not _selected("docs/assets/reviewer-mode.png")
    assert _selected(".env.example")
    assert _selected("web/.env.example")

    for private_path in (
        "../src/visiondata_gate/api.py",
        "src/../.env.example",
        "src/unsafe:name.py",
        "07_results/private-mask.png",
        "10_reports/internal.md",
        "deliverables/submission.pptx",
        "evidence/submission/private-receipt.json",
        "output/product/product.db",
        "release/candidate.zip",
        "website/data/site-data.json",
        ".env",
        ".env.local",
        ".env.production",
        "web/.env",
        "web/.env.local",
        "web/.env.production",
        "src/nested/.ENV.staging",
        "web/.env.example.local",
        "web/.env.production/secret.txt",
        "web/.env.example/secret.txt",
    ):
        assert not _selected(private_path)

    repository_ignore = (Path(__file__).resolve().parents[1] / ".gitignore").read_text(
        encoding="utf-8"
    )
    for required_public_json in (
        "PUBLIC_MIRROR_MANIFEST.json",
        "agentteams/runtime_receipt.template.json",
        "docs/CARGO_LICENSES.locked.json",
        "docs/PUBLIC_BINARY_REVIEW.json",
        "docs/SBOM.cdx.json",
        "skills/manifest.json",
        "tools/tool_lock.json",
        "web/public/public-replay.v1.json",
    ):
        assert f"!{required_public_json}" in repository_ignore.splitlines()

    public_env_example = (
        Path(__file__).resolve().parents[1] / ".env.example"
    ).read_text(encoding="utf-8")
    assert "VISIONDATA_UI_DEV_MAX_BUDGET_USD=0" in public_env_example.splitlines()


def test_public_export_injects_sha_bound_pages_workflow(
    tmp_path: Path, monkeypatch
) -> None:
    source_identity = {
        "source_commit_oid": "a" * 40,
        "source_tree_oid": "b" * 40,
        "source_worktree_clean": True,
    }
    monkeypatch.setattr(
        "tools.export_public_repository._source_identity",
        lambda: source_identity,
    )
    destination = tmp_path / "public-export"
    manifest = export(destination)
    assert manifest["schema_version"] == "visiondata-gate.public-mirror.v2"
    assert {key: manifest[key] for key in source_identity} == source_identity

    template = destination / PUBLIC_PAGES_TEMPLATE
    workflow = destination / PUBLIC_PAGES_WORKFLOW
    assert workflow.read_bytes() == template.read_bytes()

    ci_template = destination / PUBLIC_CI_TEMPLATE
    ci_workflow = destination / PUBLIC_CI_WORKFLOW
    assert ci_workflow.read_bytes() == ci_template.read_bytes()

    workflow_entry = next(
        item for item in manifest["files"] if item["path"] == PUBLIC_PAGES_WORKFLOW
    )
    assert workflow_entry["source"] == PUBLIC_PAGES_TEMPLATE
    ci_workflow_entry = next(
        item for item in manifest["files"] if item["path"] == PUBLIC_CI_WORKFLOW
    )
    assert ci_workflow_entry["source"] == PUBLIC_CI_TEMPLATE

    monkeypatch.setattr(public_repository_checker, "PROJECT_ROOT", destination)
    tracked = [item["path"] for item in manifest["files"]]
    tracked.append("PUBLIC_MIRROR_MANIFEST.json")
    assert public_repository_checker._mirror_manifest_violations(tracked) == []

    manifest_path = destination / "PUBLIC_MIRROR_MANIFEST.json"
    drifted = json.loads(manifest_path.read_text(encoding="utf-8"))
    drifted_workflow = next(
        item for item in drifted["files"] if item["path"] == PUBLIC_PAGES_WORKFLOW
    )
    drifted_workflow["source"] = "tools/templates/untrusted-pages.yml"
    manifest_path.write_text(
        json.dumps(drifted, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    assert {
        "rule": "public-pages-workflow-source-drift",
        "path": PUBLIC_PAGES_WORKFLOW,
    } in public_repository_checker._mirror_manifest_violations(tracked)

    drifted_workflow["source"] = PUBLIC_PAGES_TEMPLATE
    manifest_path.write_text(
        json.dumps(drifted, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    workflow.write_text("name: Untrusted workflow\n", encoding="utf-8", newline="\n")
    assert {
        "rule": "public-generated-copy-drift",
        "path": PUBLIC_PAGES_WORKFLOW,
    } in public_repository_checker._mirror_manifest_violations(tracked)


def test_public_repository_gate_rejects_media_and_unreviewed_binary_locations() -> None:
    violations = _path_violations(
        [
            "deliverables/demo.mp4",
            "evidence/private-receipt.json",
            "10_reports/internal.md",
            "release/private-receipt.json",
            "website/data/site-data.json",
            "docs/private.pdf",
            "screenshots/operator.png",
            "sample_data/clear/clean-val-gear.png",
        ]
    )
    rules_by_path = {(item["rule"], item["path"]) for item in violations}
    assert ("forbidden-suffix", "deliverables/demo.mp4") in rules_by_path
    for private_path in (
        "evidence/private-receipt.json",
        "10_reports/internal.md",
        "release/private-receipt.json",
        "website/data/site-data.json",
    ):
        assert ("forbidden-prefix", private_path) in rules_by_path
    assert ("forbidden-suffix", "docs/private.pdf") in rules_by_path
    assert (
        "binary-outside-reviewed-prefix",
        "screenshots/operator.png",
    ) in rules_by_path
    assert not any(item["path"].startswith("sample_data/") for item in violations)


def test_public_repository_gate_rejects_nested_env_files_except_examples() -> None:
    paths = [
        ".env",
        ".env.local",
        ".env.production",
        "web/.env",
        "web/.env.local",
        "web/.env.production",
        "src/nested/.ENV.staging",
        "web/.env.example.local",
        "web/.env.production/secret.txt",
        "web/.env.example/secret.txt",
        ".env.example",
        "web/.env.example",
    ]
    violations = _path_violations(paths)
    forbidden_paths = {
        item["path"] for item in violations if item["rule"] == "forbidden-path"
    }
    assert forbidden_paths == set(paths[:-2])


def test_public_repository_gate_rejects_private_identity_without_echoing_value() -> (
    None
):
    private_path = b"private_root=" + b"C:" + b"\\Users\\operator-name\\secret"
    violations = _content_violations(private_path, path="docs/example.md")
    assert violations == [{"rule": "private-windows-path", "path": "docs/example.md"}]

    private_email = b"operator" + b"@" + b"factory.invalid"
    assert _content_violations(private_email, path="docs/config.md") == [
        {"rule": "private-email", "path": "docs/config.md"}
    ]
    noreply_email = b"12345" + b"@users.noreply.github.com"
    assert _content_violations(noreply_email, path="docs/config.md") == []
    assert _scan_text(
        "dist/index.html",
        (b"operator" + b"@" + b"factory.invalid").decode("ascii"),
    ) == ["dist/index.html:private-email"]
    assert (
        _scan_text(
            "dist/index.html",
            (b"12345" + b"@users.noreply.github.com").decode("ascii"),
        )
        == []
    )
    pseudo_noreply = (
        b"owner" + b"@" + b"evil.example" + b"@" + b"users.noreply.github.com"
    )
    assert _scan_text(
        "dist/index.html",
        pseudo_noreply.decode("ascii"),
    ) == ["dist/index.html:private-email"]

    project_root = Path(__file__).resolve().parents[1]
    checker_source = (project_root / "tools/check_public_repository.py").read_bytes()
    assert (
        _content_violations(
            checker_source,
            path="tools/check_public_repository.py",
        )
        == []
    )


def test_public_repository_gate_covers_common_provider_secrets_without_echo() -> None:
    candidates = {
        "github-fine-grained-token": b"github_" + b"pat_" + b"A" * 24,
        "huggingface-token": b"hf_" + b"B" * 24,
        "aws-access-key": b"AKIA" + b"C" * 16,
        "slack-token": b"xoxb-" + b"D" * 24,
        "jwt-token": b"eyJ" + b"E" * 12 + b"." + b"F" * 12 + b"." + b"G" * 12,
    }
    for expected_rule, candidate in candidates.items():
        assert _content_violations(candidate, path="docs/config.md") == [
            {"rule": expected_rule, "path": "docs/config.md"}
        ]
        assert candidate.decode("ascii") not in json.dumps(
            _content_violations(candidate, path="docs/config.md")
        )


def test_public_repository_gate_rejects_non_placeholder_topology_paths() -> None:
    assert _content_violations(
        b"root=Z:\\customer-alpha\\line-7",
        path="docs/config.md",
    ) == [{"rule": "generic-windows-path", "path": "docs/config.md"}]
    assert (
        _content_violations(
            b"root=E:\\authorized-data\\visiondata # placeholder",
            path="docs/config.md",
        )
        == []
    )
    unc_path = b"root=" + (b"\\" * 2) + b"factory-nas\\secret-share\\batch"
    assert _content_violations(unc_path, path="docs/config.md") == [
        {"rule": "private-unc-path", "path": "docs/config.md"}
    ]
    json_schema_pattern = b'"pattern": "^[0-9]+\\\\.[0-9]+\\\\.[0-9]+$"'
    assert (
        _content_violations(
            json_schema_pattern,
            path="schemas/example.json",
        )
        == []
    )


def test_public_replay_manifest_remains_hash_bound_and_fail_closed() -> None:
    result = validate_manifest()
    assert result["source_mode"] == "PUBLIC_SYNTHETIC_REPLAY"
    assert result["production_release_allowed"] is False


def test_public_pages_gate_rejects_backend_authority_surfaces() -> None:
    assert _scan_runtime_surfaces("dist/app.js", 'fetch("/v1/tasks")') == [
        "dist/app.js:local-api-route"
    ]
    assert _scan_runtime_surfaces(
        "dist/app.js",
        'fetch("/api/reviewer", {method:"POST"})',
    ) == [
        "dist/app.js:reviewer-api-route",
        "dist/app.js:write-request-method",
    ]
    assert (
        _scan_runtime_surfaces(
            "dist/app.js",
            'fetch("public-replay.v1.json", {credentials:"omit"})',
        )
        == []
    )


def _write_minimal_public_dist(root: Path) -> None:
    root.mkdir(parents=True)
    (root / "index.html").write_text(
        "PUBLIC SYNTHETIC REPLAY\npublic-replay.v1.json\nproduction_release_allowed\n",
        encoding="utf-8",
    )
    (root / PUBLIC_MANIFEST.name).write_bytes(PUBLIC_MANIFEST.read_bytes())


def test_public_pages_dist_rejects_sensitive_filename_without_disclosure(
    tmp_path: Path,
) -> None:
    dist = tmp_path / "dist"
    _write_minimal_public_dist(dist)
    sensitive_name = "github_" + "pat_" + "Z" * 24 + ".txt"
    (dist / sensitive_name).write_text("synthetic public fixture\n", encoding="utf-8")

    with pytest.raises(PublicPagesValidationError) as exc_info:
        validate_dist(dist)

    message = str(exc_info.value)
    assert "dist-path:github-fine-grained-token" in message
    assert sensitive_name not in message
    assert str(dist.resolve()) not in message


def test_public_pages_dist_redacts_sensitive_prohibited_filename(
    tmp_path: Path,
) -> None:
    dist = tmp_path / "dist"
    _write_minimal_public_dist(dist)
    sensitive_name = "github_" + "pat_" + "Y" * 24 + ".map"
    (dist / sensitive_name).write_text("synthetic public fixture\n", encoding="utf-8")

    with pytest.raises(PublicPagesValidationError) as exc_info:
        validate_dist(dist)

    message = str(exc_info.value)
    assert message == "prohibited public artifact: dist-path"
    assert sensitive_name not in message
    assert str(dist.resolve()) not in message


def test_public_pages_dist_never_reports_local_absolute_root(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    _write_minimal_public_dist(dist)

    result = validate_dist(dist)
    assert result["dist"] == "public-pages-dist"
    assert str(dist.resolve()) not in json.dumps(result)

    missing = tmp_path / "operator-private-dist"
    with pytest.raises(PublicPagesValidationError) as exc_info:
        validate_dist(missing)
    assert str(missing.resolve()) not in str(exc_info.value)
    assert str(exc_info.value) == "public Pages dist not found"


def test_public_pages_dist_rejects_root_and_entry_symlinks_before_filtering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dist = tmp_path / "dist"
    _write_minimal_public_dist(dist)
    sensitive_name = "github_" + "pat_" + "W" * 24
    simulated_link = dist / sensitive_name
    simulated_link.write_text("synthetic public fixture\n", encoding="utf-8")

    path_type = type(simulated_link)
    original_is_symlink = path_type.is_symlink
    original_is_file = path_type.is_file
    monkeypatch.setattr(
        path_type,
        "is_symlink",
        lambda self: self == simulated_link or original_is_symlink(self),
    )
    monkeypatch.setattr(
        path_type,
        "is_file",
        lambda self: False if self == simulated_link else original_is_file(self),
    )

    with pytest.raises(PublicPagesValidationError) as entry_exc:
        validate_dist(dist)
    entry_message = str(entry_exc.value)
    assert entry_message == "public Pages dist contains a symbolic link: dist-path"
    assert sensitive_name not in entry_message

    monkeypatch.setattr(
        path_type,
        "is_symlink",
        lambda self: self == dist or original_is_symlink(self),
    )
    with pytest.raises(PublicPagesValidationError) as root_exc:
        validate_dist(dist)
    assert str(root_exc.value) == "public Pages dist must not be a symbolic link"
    assert str(dist.resolve()) not in str(root_exc.value)


def test_public_pages_and_snapshot_reject_simulated_windows_junctions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dist = tmp_path / "dist"
    _write_minimal_public_dist(dist)
    dist_junction = dist / "external-junction"
    dist_junction.mkdir()

    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    snapshot_junction = snapshot / "external-junction"
    snapshot_junction.mkdir()

    path_type = type(dist_junction)
    original_is_junction = path_type.is_junction
    monkeypatch.setattr(
        path_type,
        "is_junction",
        lambda self: (
            self in {dist_junction, snapshot_junction} or original_is_junction(self)
        ),
    )

    with pytest.raises(PublicPagesValidationError) as pages_exc:
        validate_dist(dist)
    assert str(pages_exc.value) == (
        "public Pages dist contains a symbolic link: external-junction"
    )

    with pytest.raises(PublicRepositoryValidationError) as snapshot_exc:
        validate_snapshot(snapshot)
    snapshot_payload = json.loads(str(snapshot_exc.value))
    assert snapshot_payload["reason"] == "snapshot contains a symbolic link"
    assert snapshot_payload["path"] == "external-junction"
    assert snapshot_payload["values_disclosed"] is False


def test_snapshot_symlink_path_is_fail_closed_and_conditionally_redacted(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target.txt"
    target.write_text("synthetic public fixture\n", encoding="utf-8")

    safe_root = tmp_path / "safe-snapshot"
    safe_root.mkdir()
    safe_link = safe_root / "safe-link.txt"
    try:
        safe_link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    with pytest.raises(PublicRepositoryValidationError) as safe_exc:
        validate_snapshot(safe_root)
    safe_payload = json.loads(str(safe_exc.value))
    assert safe_payload["status"] == "HOLD_PUBLICATION_PRIVACY"
    assert safe_payload["path"] == "safe-link.txt"
    assert safe_payload["values_disclosed"] is False

    sensitive_root = tmp_path / "sensitive-snapshot"
    sensitive_root.mkdir()
    sensitive_name = "github_" + "pat_" + "X" * 24 + ".txt"
    (sensitive_root / sensitive_name).symlink_to(target)

    with pytest.raises(PublicRepositoryValidationError) as sensitive_exc:
        validate_snapshot(sensitive_root)
    sensitive_message = str(sensitive_exc.value)
    sensitive_payload = json.loads(sensitive_message)
    assert sensitive_payload["status"] == "HOLD_PUBLICATION_PRIVACY"
    assert sensitive_payload["path"] == "tracked-path"
    assert sensitive_payload["values_disclosed"] is False
    assert sensitive_name not in sensitive_message


def test_snapshot_root_symlink_is_rejected_before_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sensitive_name = "github_" + "pat_" + "V" * 24
    root = tmp_path / sensitive_name
    root.mkdir()
    path_type = type(root)
    original_is_symlink = path_type.is_symlink
    monkeypatch.setattr(
        path_type,
        "is_symlink",
        lambda self: self == root or original_is_symlink(self),
    )

    with pytest.raises(PublicRepositoryValidationError) as exc_info:
        validate_snapshot(root)
    message = str(exc_info.value)
    payload = json.loads(message)
    assert payload["status"] == "HOLD_PUBLICATION_PRIVACY"
    assert payload["reason"] == "snapshot root is a symbolic link"
    assert payload["path"] == "snapshot-root"
    assert payload["values_disclosed"] is False
    assert sensitive_name not in message


def test_public_export_redacts_paths_and_stages_before_final_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    sensitive_relative = "src/github_" + "pat_" + "U" * 24 + ".py"
    sensitive_source = source_root / sensitive_relative
    sensitive_source.parent.mkdir()
    sensitive_source.write_text("synthetic public fixture\n", encoding="utf-8")
    destination = tmp_path / "public-export"

    monkeypatch.setattr(public_exporter, "PROJECT_ROOT", source_root)
    path_type = type(sensitive_source)
    original_is_symlink = path_type.is_symlink
    monkeypatch.setattr(
        path_type,
        "is_symlink",
        lambda self: self == sensitive_source or original_is_symlink(self),
    )
    with pytest.raises(public_exporter.PublicExportError) as path_exc:
        public_exporter._copy_files(destination, [sensitive_relative])
    assert str(path_exc.value) == "public source must not be a symlink"
    assert sensitive_relative not in str(path_exc.value)

    monkeypatch.setattr(public_exporter, "_source_identity", lambda: {"id": "stable"})
    monkeypatch.setattr(
        public_exporter,
        "_assemble_snapshot",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            public_exporter.PublicExportError("synthetic privacy rejection")
        ),
    )
    with pytest.raises(
        public_exporter.PublicExportError,
        match="synthetic privacy rejection",
    ):
        export(destination)
    assert not destination.exists()
    assert not list(tmp_path.glob(".visiondata-gate-public-*"))


def test_public_export_cli_never_reports_absolute_destination_or_oserror(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    destination = tmp_path / "operator-private-export"
    manifest = {"file_count": 3, "snapshot_sha256": "a" * 64}
    monkeypatch.setattr(public_exporter, "export", lambda _: manifest)
    monkeypatch.setattr(
        public_exporter.sys,
        "argv",
        ["export_public_repository.py", "--destination", str(destination)],
    )
    assert public_exporter.main() == 0
    success = capsys.readouterr().out
    success_payload = json.loads(success)
    assert success_payload["destination"] == "public-export-destination"
    assert str(destination.resolve()) not in success

    def raise_oserror(_: Path) -> dict[str, object]:
        raise PermissionError(f"denied: {destination.resolve()}")

    monkeypatch.setattr(public_exporter, "export", raise_oserror)
    assert public_exporter.main() == 1
    failure = capsys.readouterr().out
    failure_payload = json.loads(failure)
    assert failure_payload["reason"] == (
        "public export failed without publishing local diagnostics"
    )
    assert str(destination.resolve()) not in failure


def test_public_checkers_bound_unexpected_cli_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_path = str((tmp_path / "operator-private").resolve())

    monkeypatch.setattr(
        public_pages_checker,
        "validate_manifest",
        lambda: (_ for _ in ()).throw(PermissionError(private_path)),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["check_public_pages.py"],
    )
    assert public_pages_checker.main() == 1
    pages_output = capsys.readouterr().out
    pages_payload = json.loads(pages_output)
    assert pages_payload == {
        "status": "HOLD_PUBLIC_PAGES_PRIVACY",
        "reason": (
            "public Pages privacy check failed without publishing local diagnostics"
        ),
        "values_disclosed": False,
    }
    assert private_path not in pages_output

    monkeypatch.setattr(
        public_repository_checker,
        "validate",
        lambda *, history: (_ for _ in ()).throw(PermissionError(private_path)),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["check_public_repository.py"],
    )
    assert public_repository_checker.main() == 1
    repository_output = capsys.readouterr().out
    repository_payload = json.loads(repository_output)
    assert repository_payload == {
        "status": "HOLD_PUBLICATION_PRIVACY",
        "reason": (
            "public repository privacy check failed without publishing local "
            "diagnostics"
        ),
        "values_disclosed": False,
    }
    assert private_path not in repository_output


def test_public_export_requires_an_absent_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "already-created"
    destination.mkdir()
    monkeypatch.setattr(
        public_exporter,
        "_source_identity",
        lambda: {
            "source_commit_oid": "a" * 40,
            "source_tree_oid": "b" * 40,
            "source_worktree_clean": True,
        },
    )

    with pytest.raises(
        public_exporter.PublicExportError,
        match="destination must not already exist",
    ):
        export(destination)


def test_public_binary_review_is_exact_sha_bound_and_excludes_private_capture() -> None:
    project_root = Path(__file__).resolve().parents[1]
    manifest = json.loads(
        (project_root / PUBLIC_BINARY_REVIEW_PATH).read_text(encoding="utf-8")
    )
    paths = [PUBLIC_BINARY_REVIEW_PATH, *(item["path"] for item in manifest["files"])]
    assert _binary_review_violations(paths) == []
    assert "docs/assets/reviewer-mode.png" not in paths


def test_history_blob_classifier_is_fail_closed_and_sha_bound() -> None:
    object_id = "a" * 40
    reviewed_path = "docs/assets/reviewed.png"
    binary = b"\x89PNG\r\n\x1a\nsynthetic"
    reviewed = {reviewed_path: hashlib.sha256(binary).hexdigest()}

    assert (
        _historical_blob_violations(
            binary,
            path=reviewed_path,
            object_id=object_id,
            reviewed_binaries=reviewed,
        )
        == []
    )
    assert {
        "rule": "history-binary-sha-drift",
        "path": reviewed_path,
        "object": object_id,
    } in _historical_blob_violations(
        binary + b"drift",
        path=reviewed_path,
        object_id=object_id,
        reviewed_binaries=reviewed,
    )

    prior_binary = b"\x89PNG\r\n\x1a\nprior-synthetic"
    reviewed_revisions = {
        reviewed_path: frozenset(
            {
                hashlib.sha256(prior_binary).hexdigest(),
                hashlib.sha256(binary).hexdigest(),
            }
        )
    }
    assert (
        _historical_blob_violations(
            prior_binary,
            path=reviewed_path,
            object_id=object_id,
            reviewed_binaries=reviewed_revisions,
        )
        == []
    )
    assert {
        "rule": "history-binary-missing-semantic-review",
        "path": "docs/assets/unreviewed.png",
        "object": object_id,
    } in _historical_blob_violations(
        binary,
        path="docs/assets/unreviewed.png",
        object_id=object_id,
        reviewed_binaries=reviewed,
    )

    unknown_binary = _historical_blob_violations(
        b"opaque\0payload",
        path="docs/opaque.dat",
        object_id=object_id,
        reviewed_binaries=reviewed,
    )
    assert unknown_binary == [
        {
            "rule": "unclassified-history-binary-content",
            "path": "docs/opaque.dat",
            "object": object_id,
        }
    ]
    non_utf8 = _historical_blob_violations(
        b"\xff\xfe",
        path="docs/opaque.md",
        object_id=object_id,
        reviewed_binaries=reviewed,
    )
    assert non_utf8 == [
        {
            "rule": "non-utf8-history-text",
            "path": "docs/opaque.md",
            "object": object_id,
        }
    ]
    forbidden_archive = _historical_blob_violations(
        b"PK\x03\x04opaque",
        path="docs/private.zip",
        object_id=object_id,
        reviewed_binaries=reviewed,
    )
    assert {
        "rule": "forbidden-suffix",
        "path": "docs/private.zip",
        "object": object_id,
    } in forbidden_archive


def test_history_binary_approvals_include_valid_prior_manifest_revisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed_path = "docs/assets/reviewed.png"
    prior_binary = b"\x89PNG\r\n\x1a\nprior-synthetic"
    current_binary = b"\x89PNG\r\n\x1a\ncurrent-synthetic"

    def review_manifest(binary: bytes, reviewed_on: str) -> bytes:
        stable = {
            "schema_version": "visiondata-gate.public-binary-review.v1",
            "review_basis": "VISUAL_PIXEL_AND_METADATA_INSPECTION",
            "reviewed_on": reviewed_on,
            "reviewer_identity_included": False,
            "reviewed_file_count": 1,
            "prohibited_content_checks": ["PERSONAL_IDENTITY"],
            "files": [
                {
                    "path": reviewed_path,
                    "sha256": hashlib.sha256(binary).hexdigest(),
                    "size_bytes": len(binary),
                    "category": "SYNTHETIC_WORKBENCH_SCREENSHOT",
                    "review_result": "PASS_NO_PRIVATE_CONTENT_OBSERVED",
                }
            ],
        }
        manifest = {
            **stable,
            "manifest_sha256": hashlib.sha256(
                public_repository_checker._canonical_json_bytes(stable)
            ).hexdigest(),
        }
        return json.dumps(manifest, ensure_ascii=False).encode("utf-8")

    prior_manifest_id = "1" * 40
    current_manifest_id = "2" * 40
    payloads = {
        prior_manifest_id: review_manifest(prior_binary, "2026-08-31"),
        current_manifest_id: review_manifest(current_binary, "2026-09-02"),
    }

    def fake_git(*args: str, text: bool = False) -> bytes:
        assert args[:2] == ("cat-file", "blob")
        assert text is False
        return payloads[args[2]]

    monkeypatch.setattr(public_repository_checker, "_git", fake_git)
    approvals = public_repository_checker._reviewed_binary_history_records(
        {
            prior_manifest_id: (PUBLIC_BINARY_REVIEW_PATH,),
            current_manifest_id: (PUBLIC_BINARY_REVIEW_PATH,),
        },
        current_records={reviewed_path: hashlib.sha256(current_binary).hexdigest()},
    )
    assert approvals[reviewed_path] == frozenset(
        {
            hashlib.sha256(prior_binary).hexdigest(),
            hashlib.sha256(current_binary).hexdigest(),
        }
    )


def test_history_scan_preserves_every_path_for_deleted_binary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return result.stdout.strip()

    git("init", "--initial-branch=main")
    git("config", "user.name", "public-operator")
    git("config", "user.email", "12345@users.noreply.github.com")
    assets = tmp_path / "docs" / "assets"
    assets.mkdir(parents=True)
    binary = b"\x89PNG\r\n\x1a\nsynthetic"
    reviewed_path = "docs/assets/reviewed.png"
    deleted_path = "docs/assets/deleted.png"
    (tmp_path / reviewed_path).write_bytes(binary)
    (tmp_path / deleted_path).write_bytes(binary)
    git("add", ".")
    git("commit", "-m", "add reviewed synthetic assets")
    git("rm", deleted_path)
    git("commit", "-m", "remove obsolete synthetic asset")

    monkeypatch.setattr(public_repository_checker, "PROJECT_ROOT", tmp_path)
    object_id = git("hash-object", reviewed_path)
    objects = _history_objects()
    assert set(objects[object_id]) == {reviewed_path, deleted_path}

    violations = _scan_history_blobs(
        {object_id: objects[object_id]},
        reviewed_binaries={reviewed_path: hashlib.sha256(binary).hexdigest()},
    )
    assert {
        "rule": "history-binary-missing-semantic-review",
        "path": deleted_path,
        "object": object_id,
    } in violations
    assert all(binary.hex() not in json.dumps(item) for item in violations)


def test_history_inventory_attributes_root_commit_blob_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return result.stdout.strip()

    git("init", "--initial-branch=main")
    git("config", "user.name", "public-operator")
    git("config", "user.email", "12345@users.noreply.github.com")
    (tmp_path / "README.md").write_text(
        "synthetic public fixture\n",
        encoding="utf-8",
    )
    git("add", "README.md")
    git("commit", "-m", "root synthetic fixture")
    object_id = git("hash-object", "README.md")

    monkeypatch.setattr(public_repository_checker, "PROJECT_ROOT", tmp_path)
    objects = _history_objects()
    assert objects[object_id] == ("README.md",)
    assert HISTORY_PATH_UNAVAILABLE not in objects[object_id]


def test_history_scan_rejects_sensitive_deleted_filename_without_echoing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return result.stdout.strip()

    git("init", "--initial-branch=main")
    git("config", "user.name", "public-operator")
    git("config", "user.email", "12345@users.noreply.github.com")
    sensitive_name = "github_" + "pat_" + "D" * 24 + ".txt"
    sensitive_path = f"docs/{sensitive_name}"
    (tmp_path / "docs").mkdir()
    (tmp_path / sensitive_path).write_text(
        "synthetic public fixture\n", encoding="utf-8"
    )
    object_id = git("hash-object", sensitive_path)
    git("add", sensitive_path)
    git("commit", "-m", "add synthetic fixture")
    git("rm", sensitive_path)
    git("commit", "-m", "remove synthetic fixture")

    monkeypatch.setattr(public_repository_checker, "PROJECT_ROOT", tmp_path)
    objects = _history_objects()
    violations = _scan_history_blobs(
        {object_id: objects[object_id]},
        reviewed_binaries={},
    )
    assert {
        "rule": "github-fine-grained-token",
        "path": "historical-path",
        "object": object_id,
    } in violations
    assert sensitive_name not in json.dumps(violations)

    report_path, current_findings = _report_path_and_findings(
        sensitive_path,
        label="tracked-path",
    )
    assert report_path == "tracked-path"
    assert current_findings == [
        {"rule": "github-fine-grained-token", "path": "tracked-path"}
    ]


def test_history_inventory_rejects_deleted_gitlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return result.stdout.strip()

    git("init", "--initial-branch=main")
    git("config", "user.name", "public-operator")
    git("config", "user.email", "12345@users.noreply.github.com")
    (tmp_path / "README.md").write_text("synthetic public fixture\n", encoding="utf-8")
    git("add", "README.md")
    git("commit", "-m", "add synthetic fixture")
    commit_id = git("rev-parse", "HEAD")
    git(
        "update-index",
        "--add",
        "--cacheinfo",
        "160000",
        commit_id,
        "tmp/private-link",
    )
    git("commit", "-m", "add synthetic gitlink")
    git("rm", "--cached", "tmp/private-link")
    git("commit", "-m", "remove synthetic gitlink")

    monkeypatch.setattr(public_repository_checker, "PROJECT_ROOT", tmp_path)
    _, violations = _history_inventory()
    assert {
        "rule": "unscanned-history-gitlink",
        "path": "tmp/private-link",
        "object": commit_id,
    } in violations
    assert {
        "rule": "forbidden-prefix",
        "path": "tmp/private-link",
        "object": commit_id,
    } in violations


def test_history_scan_rejects_reachable_blob_without_tree_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def git(*args: str, input_bytes: bytes | None = None) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            input=input_bytes,
        )
        return result.stdout.decode("ascii").strip()

    git("init", "--initial-branch=main")
    git("config", "user.name", "public-operator")
    git("config", "user.email", "12345@users.noreply.github.com")
    (tmp_path / "README.md").write_text("synthetic public fixture\n", encoding="utf-8")
    git("add", "README.md")
    git("commit", "-m", "add synthetic fixture")
    blob = b"opaque\0private-fixture"
    object_id = git("hash-object", "-w", "--stdin", input_bytes=blob)
    git("tag", "-a", "blob-fixture", object_id, "-m", "synthetic blob tag")
    tag_object_id = git("rev-parse", "blob-fixture^{tag}")

    monkeypatch.setattr(public_repository_checker, "PROJECT_ROOT", tmp_path)
    objects = _history_objects()
    assert objects[object_id] == (HISTORY_PATH_UNAVAILABLE,)
    assert (tag_object_id, "tag") in _revision_metadata_objects()
    assert _scan_commit_identities() == []

    violations = _scan_history_blobs(
        {object_id: objects[object_id]},
        reviewed_binaries={},
    )
    assert {
        "rule": "history-blob-without-tree-path",
        "path": HISTORY_PATH_UNAVAILABLE,
        "object": object_id,
    } in violations
    assert all(blob.hex() not in json.dumps(item) for item in violations)


def test_revision_metadata_scans_names_messages_and_annotated_tags() -> None:
    object_id = "b" * 40
    private_path = b"C:" + b"\\Users\\operator-name\\secret"
    commit = (
        b"tree "
        + b"c" * 40
        + b"\n"
        + b"author public-operator <12345@users.noreply.github.com> 0 +0000\n"
        + b"committer public-operator <12345@users.noreply.github.com> 0 +0000\n\n"
        + b"reference "
        + private_path
        + b"\n"
    )
    assert {
        "rule": "private-windows-path",
        "path": "commit-message",
        "object": object_id,
    } in _revision_metadata_violations(
        commit,
        object_id=object_id,
        object_kind="commit",
    )

    tag = (
        b"object "
        + b"c" * 40
        + b"\ntype commit\ntag release\n"
        + b"tagger public-operator <12345@users.noreply.github.com> 0 +0000\n\n"
        + b"token "
        + b"github_"
        + b"pat_"
        + b"A" * 24
        + b"\n"
    )
    assert {
        "rule": "github-fine-grained-token",
        "path": "tag-message",
        "object": object_id,
    } in _revision_metadata_violations(
        tag,
        object_id=object_id,
        object_kind="tag",
    )
    assert _revision_metadata_violations(
        commit + b"\0",
        object_id=object_id,
        object_kind="commit",
    ) == [{"rule": "nul-in-commit-metadata", "object": object_id}]

    token = b"github_" + b"pat_" + b"B" * 24
    commit_with_header_secret = (
        b"tree "
        + b"c" * 40
        + b"\nauthor public-operator <12345@users.noreply.github.com> 0 +0000\n"
        + b"committer public-operator <12345@users.noreply.github.com> 0 +0000\n"
        + b"encoding "
        + token
        + b"\n\nsynthetic message\n"
    )
    assert {
        "rule": "github-fine-grained-token",
        "path": "commit-header",
        "object": object_id,
    } in _revision_metadata_violations(
        commit_with_header_secret,
        object_id=object_id,
        object_kind="commit",
    )

    commit_with_email_secret = (
        b"tree "
        + b"c" * 40
        + b"\nauthor public-operator <"
        + token
        + b"@users.noreply.github.com> 0 +0000\n"
        + b"committer public-operator <12345@users.noreply.github.com> 0 +0000\n\n"
        + b"synthetic message\n"
    )
    assert {
        "rule": "github-fine-grained-token",
        "path": "commit-author-email",
        "object": object_id,
    } in _revision_metadata_violations(
        commit_with_email_secret,
        object_id=object_id,
        object_kind="commit",
    )

    generic_private_path = b"D:" + b"\\factory\\private\\artifact"
    commit_with_generic_path = (
        b"tree "
        + b"c" * 40
        + b"\nauthor public-operator <12345@users.noreply.github.com> 0 +0000\n"
        + b"committer public-operator <12345@users.noreply.github.com> 0 +0000\n\n"
        + b"reference "
        + generic_private_path
        + b"\n"
    )
    assert {
        "rule": "generic-windows-path",
        "path": "commit-message",
        "object": object_id,
    } in _revision_metadata_violations(
        commit_with_generic_path,
        object_id=object_id,
        object_kind="commit",
    )


def test_revision_metadata_scans_nested_reachable_annotated_tag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return result.stdout.strip()

    git("init", "--initial-branch=main")
    git("config", "user.name", "public-operator")
    git("config", "user.email", "12345@users.noreply.github.com")
    (tmp_path / "README.md").write_text("synthetic public fixture\n", encoding="utf-8")
    git("add", "README.md")
    git("commit", "-m", "add synthetic fixture")
    private_path = "C:" + "\\Users\\operator-name\\secret"
    git("tag", "-a", "inner-fixture", "HEAD", "-m", f"reference {private_path}")
    inner_tag_object = git("rev-parse", "inner-fixture^{tag}")
    git("tag", "-a", "outer-fixture", inner_tag_object, "-m", "synthetic outer tag")
    git("tag", "-d", "inner-fixture")

    monkeypatch.setattr(public_repository_checker, "PROJECT_ROOT", tmp_path)
    assert (inner_tag_object, "tag") in _revision_metadata_objects()
    violations = _scan_commit_identities()
    assert {
        "rule": "private-windows-path",
        "path": "tag-message",
        "object": inner_tag_object,
    } in violations


def test_pseudo_noreply_identity_and_content_are_rejected() -> None:
    object_id = "d" * 40
    pseudo_noreply = (
        b"owner" + b"@" + b"evil.example" + b"@" + b"users.noreply.github.com"
    )
    assert {
        "rule": "private-email",
        "path": "commit-message",
        "object": object_id,
    } in _content_violations(
        pseudo_noreply,
        path="commit-message",
        object_id=object_id,
    )

    commit = (
        b"tree "
        + b"c" * 40
        + b"\nauthor public-operator <"
        + pseudo_noreply
        + b"> 0 +0000\n"
        + b"committer public-operator <12345@users.noreply.github.com> 0 +0000\n\n"
        + b"synthetic message\n"
    )
    assert {
        "rule": "author-email-not-noreply",
        "object": object_id,
    } in _revision_metadata_violations(
        commit,
        object_id=object_id,
        object_kind="commit",
    )


def test_git_ref_names_are_scanned_without_echoing_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def git(*args: str) -> None:
        subprocess.run(
            ["git", *args],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    git("init", "--initial-branch=main")
    git("config", "user.name", "public-operator")
    git("config", "user.email", "12345@users.noreply.github.com")
    (tmp_path / "README.md").write_text("synthetic public fixture\n", encoding="utf-8")
    git("add", "README.md")
    git("commit", "-m", "add synthetic fixture")
    secret_ref = "github_" + "pat_" + "C" * 24
    git("branch", secret_ref)

    monkeypatch.setattr(public_repository_checker, "PROJECT_ROOT", tmp_path)
    violations = _scan_ref_names()
    assert {
        "rule": "github-fine-grained-token",
        "path": "git-ref-name",
    } in violations
    assert secret_ref not in json.dumps(violations)


def test_replace_refs_are_ignored_and_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return result.stdout.strip()

    git("init", "--initial-branch=main")
    git("config", "user.name", "public-operator")
    git("config", "user.email", "12345@users.noreply.github.com")
    (tmp_path / "README.md").write_text("synthetic public fixture\n", encoding="utf-8")
    git("add", "README.md")
    git("commit", "-m", "add clean fixture")
    clean_commit = git("rev-parse", "HEAD")
    (tmp_path / "docs").mkdir()
    private_path = "docs/private.dat"
    (tmp_path / private_path).write_bytes(b"opaque\0payload")
    private_blob = git("hash-object", private_path)
    git("add", private_path)
    git("commit", "-m", "add opaque fixture")
    replaced_commit = git("rev-parse", "HEAD")
    git("replace", replaced_commit, clean_commit)

    monkeypatch.setattr(public_repository_checker, "PROJECT_ROOT", tmp_path)
    objects = _history_objects()
    assert private_path in objects[private_blob]
    assert {
        "rule": "git-replace-ref-present",
        "path": "git-ref-name",
    } in _scan_ref_names()
    assert {
        "rule": "unclassified-history-binary-content",
        "path": private_path,
        "object": private_blob,
    } in _scan_history_blobs(
        {private_blob: objects[private_blob]},
        reviewed_binaries={},
    )


def test_history_environment_rejects_shallow_and_grafts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graft_path = tmp_path / "grafts"
    graft_path.write_text("synthetic graft\n", encoding="utf-8")

    def fake_git(*args: str, text: bool = False) -> str | bytes:
        assert text is True
        if args == ("rev-parse", "--is-shallow-repository"):
            return "true\n"
        if args == ("rev-parse", "--git-path", "info/grafts"):
            return str(graft_path)
        raise AssertionError(args)

    monkeypatch.setattr(public_repository_checker, "_git", fake_git)
    assert _history_environment_violations() == [
        {"rule": "shallow-history-not-complete"},
        {"rule": "git-grafts-present"},
    ]
