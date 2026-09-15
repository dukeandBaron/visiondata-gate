"""Product-facing documentation links to bounded evidence, not private run IDs."""

from pathlib import Path

from tools.audit_worktree_namespaces import (
    CURRENT_CLAIM_REQUIREMENTS,
    _audit_current_claims,
)


def _claims_copy(tmp_path):
    root = Path(__file__).resolve().parents[1]
    for name in CURRENT_CLAIM_REQUIREMENTS:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((root / name).read_bytes())
    return tmp_path


def test_product_entrypoints_need_boundary_and_trace_links_not_internal_run_ids(
    tmp_path,
):
    root = _claims_copy(tmp_path)
    report = _audit_current_claims(root, require_local_evidence=False)
    assert report["status"] == "PASS", report["missing_requirements"]


def test_removing_factory_metric_boundary_is_rejected(tmp_path):
    root = _claims_copy(tmp_path)
    readme = root / "docs/README_STATUS_AND_EVIDENCE.md"
    readme.write_text(
        readme.read_text(encoding="utf-8").replace(
            "NOT_MEASURED_PENDING_ADJUDICATION", "MEASURED_AND_CONFIRMED"
        ),
        encoding="utf-8",
    )
    report = _audit_current_claims(root, require_local_evidence=False)
    assert report["status"] == "FAIL"
    assert any(
        item["path"] == "docs/README_STATUS_AND_EVIDENCE.md"
        and "NOT_MEASURED_PENDING_ADJUDICATION" in item["missing_tokens"]
        for item in report["missing_requirements"]
    )


def test_removing_entrypoint_trace_link_is_rejected(tmp_path):
    root = _claims_copy(tmp_path)
    readme = root / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8").replace(
            "docs/README_STATUS_AND_EVIDENCE.md", "missing-status.md"
        ),
        encoding="utf-8",
    )
    result = _audit_current_claims(root, require_local_evidence=False)
    assert result["status"] == "FAIL"
    assert any(item["path"] == "README.md" for item in result["missing_requirements"])


def test_public_docs_do_not_certify_missing_historical_release(tmp_path):
    root = _claims_copy(tmp_path)
    result = _audit_current_claims(root, require_local_evidence=True)
    assert result["status"] == "FAIL"
    assert result["local_evidence_required"] is True
    assert any(
        item["status"] == "MISSING_LOCAL_EVIDENCE"
        for item in result["local_evidence_checks"]
    )
