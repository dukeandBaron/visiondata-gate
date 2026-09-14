from __future__ import annotations

import csv
import io
import json
import shutil
import stat
import zipfile
from pathlib import Path

import pytest

from visiondata_gate.audit_envelope import canonical_jcs_bytes
from visiondata_gate.contracts import (
    AgentOpinion,
    CouncilTrace,
    EvaluationResult,
    EvidenceStatus,
    Finding,
    GateDecision,
    GateResult,
    Severity,
    RuleCheck,
    RuleCheckResult,
    ToolTrace,
    WorkOrder,
)
from visiondata_gate.evidence import (
    canonical_json_bytes,
    build_evidence_matrix_records,
    evidence_matrix_csv_bytes,
    findings_csv_bytes,
    sha256_bytes,
    write_evidence_artifacts,
)
from visiondata_gate.goal3_public_evidence import (
    GOAL3_PUBLIC_JSON_NAMES,
    GOAL3_PUBLIC_REQUIRED_PATHS,
    GOAL3_PUBLIC_ROOT,
    GOAL3_PUBLIC_SCREENSHOT_NAMES,
    Goal3PublicEvidenceError,
    _SEMIFINAL_SOURCE_MANIFEST_FIELDS,
    _safe_public_manifest,
    inspect_public_png,
    verify_goal3_public_evidence,
)
from visiondata_gate.package import (
    CURRENT_GOAL3_PUBLIC_EVIDENCE_PATHS,
    DEFAULT_SUBMISSION_REQUIRED_PATHS,
    FILE_MODE,
    MANIFEST_NAME,
    MANIFEST_SCHEMA,
    ZIP_EPOCH,
    PackageSecurityError,
    audit_submission_zip,
    build_deterministic_zip,
    scan_bytes_for_credentials,
    scan_bytes_for_private_paths,
    validate_archive_path,
)
from visiondata_gate.reporting import offline_html_bytes, write_offline_html
from visiondata_gate.runtime_models import ScenarioProfile


def _finding(
    finding_id: str = "F-001",
    *,
    code: str = "CROSS_SPLIT_EXACT_DUPLICATE",
    summary: str = "同一来源进入 train 与 test",
) -> Finding:
    return Finding(
        finding_id=finding_id,
        code=code,
        severity=Severity.CRITICAL,
        tool="duplicate-leakage-v1",
        sample_ids=["sample-b", "sample-a"],
        summary=summary,
        evidence={"splits": ["train", "test"], "distance": 0},
        evidence_status=EvidenceStatus.VERIFIED,
        recommended_action="REMOVE_OR_REPARTITION",
    )


def _gate_result(*, summary: str = "同一来源进入 train 与 test") -> GateResult:
    finding = _finding(summary=summary)
    opinion = AgentOpinion(
        role_id="ai-leakage-auditor",
        display_name="AI 重复与泄漏分析角色",
        focus="只解释白名单重复检测结果",
        evidence_refs=[finding.finding_id],
        claims=["跨 split 精确重复是冻结合同的结构型失败"],
        challenge="是否存在来源绑定错误？",
        recommendation=GateDecision.QUARANTINE,
        confidence_axes={"E": "high", "T": "high", "A": "high", "M": "high"},
        limitations=["不是数据授权结论"],
    )
    return GateResult(
        run_id="run-fixed-001",
        batch_id="batch-dirty-001",
        contract_id="visiondata-image-demo-v1",
        input_sha256="0" * 64,
        policy_version="gate-policy-1.0",
        decision=GateDecision.QUARANTINE,
        decision_reason="critical structural finding blocks sandbox release",
        metrics={
            "finding_count": 1,
            "sample_count": 12,
            "critical_bad_release_rate": 0.0,
        },
        findings=[finding],
        tool_trace=[
            ToolTrace(
                sequence=1,
                tool="duplicate-leakage-v1",
                status="ok",
                input_sha256="0" * 64,
                parameters={"distance": 0},
                result_sha256="1" * 64,
                finding_ids=[finding.finding_id],
            )
        ],
        council_trace=CouncilTrace(
            backend="offline-rules",
            shared_model_disclosure="No external model was invoked in this fixture.",
            independent_opinions=[opinion],
            cross_examination=["反方确认该 finding 不能由角色投票覆盖。"],
            unresolved_objections=[],
        ),
        work_orders=[
            WorkOrder(
                work_order_id="WO-001",
                action="REMOVE_OR_REPARTITION",
                priority=Severity.CRITICAL,
                reason_codes=[finding.code],
                sample_ids=finding.sample_ids,
                replacement_requirements={"preserve_split_isolation": True},
            )
        ],
    )


def _evaluation() -> EvaluationResult:
    return EvaluationResult(
        batch_id="batch-dirty-001",
        truth_issue_count=1,
        predicted_issue_count=1,
        true_positive_count=1,
        false_positive_count=0,
        false_negative_count=0,
        precision=1.0,
        recall=1.0,
        f1=1.0,
        critical_bad_release_rate=0.0,
        false_quarantine_rate=0.0,
        work_order_recall=1.0,
        irrelevant_work_order_rate=0.0,
        post_repair_correct_pass=True,
        notes=["synthetic fixture only"],
    )


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, ZIP_EPOCH)
    info.create_system = 3
    info.compress_type = zipfile.ZIP_STORED
    info.external_attr = (stat.S_IFREG | FILE_MODE) << 16
    return info


def _write_deterministic_zip(path: Path, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        for name in sorted(entries):
            archive.writestr(_zip_info(name), entries[name])


def _manifest_for(entries: dict[str, bytes]) -> bytes:
    manifest = {
        "algorithm": "SHA-256",
        "archive_format": {
            "compression": "stored",
            "file_mode": "0644",
            "timestamp": "1980-01-01T00:00:00",
        },
        "files": [
            {"path": name, "size": len(data), "sha256": sha256_bytes(data)}
            for name, data in sorted(entries.items())
        ],
        "schema_version": MANIFEST_SCHEMA,
    }
    return canonical_json_bytes(manifest)


def test_canonical_json_is_stable_and_rejects_ambiguous_values() -> None:
    left = {"z": [3, 2, 1], "a": {"中文": True, "value": 1.25}}
    right = {"a": {"value": 1.25, "中文": True}, "z": [3, 2, 1]}

    expected = '{"a":{"value":1.25,"中文":true},"z":[3,2,1]}\n'.encode()
    assert canonical_json_bytes(left) == expected
    assert canonical_json_bytes(left) == canonical_json_bytes(right)
    with pytest.raises(ValueError, match="NaN"):
        canonical_json_bytes({"bad": float("nan")})
    with pytest.raises(TypeError, match="unordered sets"):
        canonical_json_bytes({"bad": {"a", "b"}})


def test_findings_csv_has_fixed_columns_codes_and_order() -> None:
    second = _finding("F-002", code="LOW_SHARPNESS")
    first = _finding("F-001", code="DECODE_FAILURE")

    data = findings_csv_bytes([second, first])
    assert b"\r\n" not in data
    rows = list(csv.DictReader(io.StringIO(data.decode("utf-8"))))

    assert [row["finding_id"] for row in rows] == ["F-001", "F-002"]
    assert [row["code"] for row in rows] == ["DECODE_FAILURE", "LOW_SHARPNESS"]
    assert rows[0]["sample_ids"] == "sample-a|sample-b"
    assert json.loads(rows[0]["evidence_json"]) == {
        "distance": 0,
        "splits": ["train", "test"],
    }


def test_evidence_matrix_links_finding_and_work_order_to_failed_rules() -> None:
    finding = _finding(
        "F-202",
        code="CROSS_SPLIT_NEAR_DUPLICATE",
        summary="材料级别的重复样本需去重或重分区",
    )
    wo = WorkOrder(
        work_order_id="WO-202",
        action="REMOVE_OR_REPARTITION",
        priority=Severity.CRITICAL,
        reason_codes=[finding.code, finding.finding_id],
        sample_ids=finding.sample_ids,
    )
    council = CouncilTrace(
        backend="test",
        shared_model_disclosure="fixed",
        independent_opinions=[],
        cross_examination=[],
        unresolved_objections=[],
    )
    result = GateResult(
        run_id="run-matrix",
        batch_id="batch-matrix",
        contract_id="visiondata-image-demo-v1",
        input_sha256="0" * 64,
        policy_version="gate-policy-1.0",
        decision=GateDecision.QUARANTINE,
        decision_reason="test-matrix",
        metrics={"finding_count": 1, "tool_count": 4, "tool_error_count": 0},
        findings=[finding],
        tool_trace=[
            ToolTrace(
                sequence=1,
                tool="duplicate_leakage",
                status="ok",
                input_sha256="0" * 64,
                parameters={"distance": 0},
                result_sha256="1" * 64,
                finding_ids=[finding.finding_id],
            )
        ],
        council_trace=council,
        work_orders=[wo],
        rule_checks=[
            RuleCheck(
                check_id="RC-GOVERNANCE-SCOPE",
                status=RuleCheckResult.FAIL,
                detail="test",
                related_refs=["GOVERNANCE", finding.finding_id],
            ),
            RuleCheck(
                check_id="RC-TOOL-COUNT",
                status=RuleCheckResult.PASS,
                detail="ok",
                related_refs=["tool_count"],
            ),
            RuleCheck(
                check_id="RC-COUNTERFACTUAL-REMOVE-1",
                status=RuleCheckResult.FAIL,
                detail="counterfactual drift",
                related_refs=["finding:" + finding.finding_id],
            ),
        ],
        boundary_notice="ok",
    )

    rows = build_evidence_matrix_records(result)
    assert len(rows) == 2
    by_check = {row["failed_rule_checks"]: row for row in rows}
    assert by_check["RC-GOVERNANCE-SCOPE"]["work_order_ids"] == wo.work_order_id
    assert by_check["RC-COUNTERFACTUAL-REMOVE-1"]["work_order_ids"] == wo.work_order_id

    row = by_check["RC-GOVERNANCE-SCOPE"]
    assert row["finding_id"] == finding.finding_id
    assert row["finding_code"] == finding.code
    assert row["work_order_ids"] == wo.work_order_id
    assert "RC-GOVERNANCE-SCOPE" in row["failed_rule_checks"]
    reason_payload = json.loads(row["reason_trace"])
    assert reason_payload["check_id"] == "RC-GOVERNANCE-SCOPE"
    assert reason_payload["work_order"] == wo.work_order_id
    assert row["evidence_span"].startswith(
        f"finding={finding.finding_id}|tool={finding.tool}"
    )

    csv_text = evidence_matrix_csv_bytes(rows).decode("utf-8")
    csv_rows = list(csv.DictReader(io.StringIO(csv_text)))
    assert csv_rows[0]["tool"] == finding.tool
    assert csv_rows[0]["finding_code"] == finding.code
    assert {row["failed_rule_checks"] for row in csv_rows} == {
        "RC-COUNTERFACTUAL-REMOVE-1",
        "RC-GOVERNANCE-SCOPE",
    }
    assert all("reason_trace" in row for row in csv_rows)


def test_evidence_matrix_policy_only_rows_keep_machine_parseable_reason_trace() -> None:
    work_order = WorkOrder(
        work_order_id="WO-001",
        action="REMOVE_OR_REPARTITION",
        priority=Severity.CRITICAL,
        reason_codes=["RC-COUNTERFACTUAL-RULE-STABILITY-1"],
        sample_ids=["sample-a"],
    )
    council = CouncilTrace(
        backend="test",
        shared_model_disclosure="fixed",
        independent_opinions=[],
        cross_examination=[],
        unresolved_objections=[],
    )
    result = GateResult(
        run_id="run-policy-only",
        batch_id="batch-matrix",
        contract_id="visiondata-image-demo-v1",
        input_sha256="0" * 64,
        policy_version="gate-policy-1.0",
        decision=GateDecision.QUARANTINE,
        decision_reason="policy-only",
        metrics={"tool_count": 1},
        findings=[],
        tool_trace=[],
        council_trace=council,
        work_orders=[work_order],
        rule_checks=[
            RuleCheck(
                check_id="RC-COUNTERFACTUAL-RULE-STABILITY-1",
                status=RuleCheckResult.FAIL,
                detail="policy only path",
                related_refs=["policy-only"],
            )
        ],
    )

    rows = build_evidence_matrix_records(result)
    assert len(rows) == 1
    row = rows[0]
    assert row["tool"] == "policy"
    assert row["work_order_ids"] == work_order.work_order_id
    payload = json.loads(row["reason_trace"])
    assert payload["check_id"] == "RC-COUNTERFACTUAL-RULE-STABILITY-1"
    assert payload["work_order"] == work_order.work_order_id


def test_evidence_and_single_file_html_are_deterministic_and_escaped(
    tmp_path: Path,
) -> None:
    result = _gate_result(summary='<img src="remote" onerror="bad">')
    evaluation = _evaluation()
    first = tmp_path / "first"
    second = tmp_path / "second"

    hashes_one = write_evidence_artifacts(first, result, evaluation)
    hashes_two = write_evidence_artifacts(second, result, evaluation)
    assert hashes_one == hashes_two
    for relative in hashes_one:
        assert (first / relative).read_bytes() == (second / relative).read_bytes()

    html_one = offline_html_bytes(result, evaluation)
    html_two = offline_html_bytes(result, evaluation)
    assert html_one == html_two
    lowered = html_one.lower()
    assert b"<script" not in lowered
    assert b"http://" not in lowered and b"https://" not in lowered
    assert b"<img src=" not in lowered
    assert b"&lt;img src=&quot;remote&quot; onerror=&quot;bad&quot;&gt;" in lowered
    assert "AI Expert Council（非真人专家）" in html_one.decode("utf-8")

    digest = write_offline_html(first / "report.html", result, evaluation)
    assert digest == sha256_bytes((first / "report.html").read_bytes())


def test_evidence_artifacts_include_rule_package_snapshot_when_profile_provided(
    tmp_path: Path,
) -> None:
    result = _gate_result(summary="rule package snapshot")
    first = tmp_path / "first"
    second = tmp_path / "second"

    hashes_one = write_evidence_artifacts(
        first,
        result,
        _evaluation(),
        scenario_profile=ScenarioProfile.INDUSTRIAL,
    )
    hashes_two = write_evidence_artifacts(
        second,
        result,
        _evaluation(),
        scenario_profile=ScenarioProfile.INDUSTRIAL,
    )
    assert hashes_one == hashes_two
    snapshot_path = first / "rule_package_snapshot.json"
    assert snapshot_path.is_file()
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert payload["scenario_profile"] == "industrial"
    assert "rule_packages" in payload
    assert "enabled_checks" in payload


def test_zip_is_byte_reproducible_and_clean_extract_audits(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "src").mkdir(parents=True)
    (source / "README.md").write_text("# safe\n", encoding="utf-8", newline="\n")
    (source / "src" / "main.py").write_text(
        "print('ok')\n", encoding="utf-8", newline="\n"
    )

    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    build_one = build_deterministic_zip(source, first)
    build_two = build_deterministic_zip(source, second)

    assert first.read_bytes() == second.read_bytes()
    assert build_one.zip_sha256 == build_two.zip_sha256
    with zipfile.ZipFile(first) as archive:
        infos = archive.infolist()
        assert [info.filename for info in infos] == sorted(
            info.filename for info in infos
        )
        assert all(info.date_time == ZIP_EPOCH for info in infos)
        assert all(
            stat.S_IMODE(info.external_attr >> 16) == FILE_MODE for info in infos
        )
        assert all(info.compress_type == zipfile.ZIP_STORED for info in infos)
        manifest_bytes = archive.read(MANIFEST_NAME)
        assert manifest_bytes == canonical_json_bytes(json.loads(manifest_bytes))

    audit = audit_submission_zip(first, required_paths=["README.md", "src/main.py"])
    assert audit.ok, audit.to_dict()
    assert audit.clean_extract_verified
    assert audit.verified_file_count == 2


def test_builder_prunes_excluded_tree_before_resolving_descendants(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    excluded = source / "tmp" / "junction-target"
    excluded.mkdir(parents=True)
    (source / "README.md").write_text("# safe\n", encoding="utf-8")
    (excluded / "outside.txt").write_text("must not be visited\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()

    real_resolve = Path.resolve

    def resolve_like_excluded_junction(
        path: Path,
        strict: bool = False,
    ) -> Path:
        if excluded == path or excluded in path.parents:
            return outside / path.name
        return real_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", resolve_like_excluded_junction)
    archive_path = tmp_path / "safe.zip"
    build_deterministic_zip(source, archive_path)

    with zipfile.ZipFile(archive_path) as archive:
        assert set(archive.namelist()) == {"README.md", MANIFEST_NAME}


def test_builder_still_blocks_escape_outside_excluded_trees(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    included = source / "assets"
    included.mkdir(parents=True)
    candidate = included / "escape.txt"
    candidate.write_text("unsafe\n", encoding="utf-8")
    outside = tmp_path / "outside" / candidate.name

    real_resolve = Path.resolve

    def resolve_like_unexcluded_junction(
        path: Path,
        strict: bool = False,
    ) -> Path:
        if path == candidate:
            return outside
        return real_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", resolve_like_unexcluded_junction)
    with pytest.raises(PackageSecurityError, match="source_escape"):
        build_deterministic_zip(source, tmp_path / "blocked.zip")


def test_builder_excludes_generated_intermediates_without_hiding_evidence(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    deliverables = source / "deliverables"
    generated_metadata = source / "src" / "VisionData_Gate.EGG-INFO"
    generated_output = source / "Output"
    browser_trace = source / ".playwright-cli"
    rust_target = source / "web" / "src-tauri" / "target" / "debug"
    tauri_gen = source / "web" / "src-tauri" / "gen" / "schemas"
    qa_run = source / "deliverables" / "_qa" / "run_20260812T000000+0800"
    deliverables.mkdir(parents=True)
    generated_metadata.mkdir(parents=True)
    generated_output.mkdir()
    browser_trace.mkdir()
    rust_target.mkdir(parents=True)
    tauri_gen.mkdir(parents=True)
    qa_run.mkdir(parents=True)
    (source / "README.md").write_text("# safe\n", encoding="utf-8")
    (source / "Submission_Manifest.json").write_text(
        '{"stale":true}\n',
        encoding="utf-8",
    )
    (deliverables / "deck.pptx.inspect.ndjson").write_text(
        '{"kind":"slide"}\n',
        encoding="utf-8",
    )
    current_deck = deliverables / "GOAI_VisionDataGate_Semifinal_RC3_20260831.pdf"
    current_deck.write_bytes(b"%PDF-current")
    (rust_target / "visiondata-gate-desktop.exe").write_bytes(b"generated")
    (tauri_gen / "desktop-schema.json").write_text("{}\n", encoding="utf-8")
    (source / "web" / "tsconfig.app.tsbuildinfo").write_text(
        "generated\n", encoding="utf-8"
    )
    (generated_metadata / "PKG-INFO").write_text(
        "generated build metadata\n",
        encoding="utf-8",
    )
    (generated_output / "scratch.json").write_text(
        '{"temporary":true}\n',
        encoding="utf-8",
    )
    (browser_trace / "page.yml").write_text("browser trace\n", encoding="utf-8")
    (qa_run / "qa_summary.json").write_text('{"temporary":true}\n', encoding="utf-8")

    archive_path = tmp_path / "submission.zip"
    build_deterministic_zip(source, archive_path)

    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
    assert "deliverables/deck.pptx.inspect.ndjson" not in names
    assert "src/VisionData_Gate.EGG-INFO/PKG-INFO" not in names
    assert "Output/scratch.json" not in names
    assert ".playwright-cli/page.yml" not in names
    assert "deliverables/_qa/run_20260812T000000+0800/qa_summary.json" not in names
    assert "Submission_Manifest.json" not in names
    assert "deliverables/curated.ndjson" not in names
    assert "web/src-tauri/target/debug/visiondata-gate-desktop.exe" not in names
    assert "web/src-tauri/gen/schemas/desktop-schema.json" not in names
    assert "web/tsconfig.app.tsbuildinfo" not in names
    assert "deliverables/GOAI_VisionDataGate_Semifinal_RC3_20260831.pdf" in names


def test_builder_keeps_only_public_env_templates(tmp_path: Path) -> None:
    source = tmp_path / "source"
    web = source / "web"
    web.mkdir(parents=True)
    (source / ".env.example").write_text("VISIONDATA_API_KEY=\n", encoding="utf-8")
    (web / ".env.example").write_text(
        "VITE_VISIONDATA_API_BASE_URL=http://127.0.0.1:8787\n",
        encoding="utf-8",
    )
    (source / ".env.local").write_text("VISIONDATA_API_KEY=private\n", encoding="utf-8")
    (web / ".env.production").write_text("PRIVATE=blocked\n", encoding="utf-8")

    archive_path = tmp_path / "submission.zip"
    build_deterministic_zip(source, archive_path)

    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
    assert ".env.example" in names
    assert "web/.env.example" in names
    assert ".env.local" not in names
    assert "web/.env.production" not in names


def test_builder_excludes_legacy_ui_and_release_tools(tmp_path: Path) -> None:
    source = tmp_path / "source"
    current_web = source / "web" / "src"
    legacy_website = source / "website"
    legacy_reviewer = source / "reviewer_workbench"
    tools = source / "tools"
    current_web.mkdir(parents=True)
    legacy_website.mkdir()
    legacy_reviewer.mkdir()
    tools.mkdir()
    (current_web / "main.tsx").write_text("export {};\n", encoding="utf-8")
    (source / "app.py").write_text("print('legacy')\n", encoding="utf-8")
    (legacy_website / "index.html").write_text("old\n", encoding="utf-8")
    (legacy_reviewer / "index.html").write_text("old\n", encoding="utf-8")
    (tools / "check_release_assets.py").write_text(
        "raise SystemExit\n", encoding="utf-8"
    )

    archive_path = tmp_path / "submission.zip"
    build_deterministic_zip(source, archive_path)

    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
    assert "web/src/main.tsx" in names
    assert "app.py" not in names
    assert "website/index.html" not in names
    assert "reviewer_workbench/index.html" not in names
    assert "tools/check_release_assets.py" not in names


def test_builder_excludes_product_database_and_sidecars(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("# safe\n", encoding="utf-8")
    sensitive_names = (
        "product.sqlite3",
        "product.sqlite3-wal",
        "product.sqlite3-shm",
        "customer.db",
        "customer.db-wal",
        "customer.db-shm",
    )
    for name in sensitive_names:
        (source / name).write_bytes(b"secret@example.com")

    archive_path = tmp_path / "submission.zip"
    build_deterministic_zip(source, archive_path)
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
    assert "README.md" in names
    assert not (set(sensitive_names) & names)


def test_builder_excludes_detached_receipt_without_excluding_other_json(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    deliverables = source / "deliverables"
    docs = source / "docs"
    deliverables.mkdir(parents=True)
    docs.mkdir()
    (source / "README.md").write_text("# safe\n", encoding="utf-8")
    (deliverables / "candidate.receipt.json").write_text(
        '{"zip_sha256":"detached"}\n', encoding="utf-8"
    )
    (docs / "audit.json").write_text('{"ok":true}\n', encoding="utf-8")

    archive_path = tmp_path / "submission.zip"
    build_deterministic_zip(source, archive_path)

    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
    assert "deliverables/candidate.receipt.json" not in names
    assert "docs/audit.json" in names


def test_builder_keeps_only_curated_submission_media_and_current_qa(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    deliverables = source / "deliverables"
    qa = deliverables / "_qa"
    current_reports = source / "10_reports"
    qa.mkdir(parents=True)
    current_reports.mkdir()
    (source / "README.md").write_text("# safe\n", encoding="utf-8")
    current_files = {
        "GOAI_VisionDataGate_Semifinal_RC3_20260831.pptx": b"current-pptx",
        "GOAI_VisionDataGate_Semifinal_RC3_20260831.pdf": b"current-pdf",
        "VisionDataGate_GOAI_Semifinal_RC3_20260831.mp4": b"current-video",
    }
    for name, payload in current_files.items():
        (deliverables / name).write_bytes(payload)
    (deliverables / "GOAI_VisionDataGate_BoundlessAgents_20260816.pptx").write_bytes(
        b"historical-pptx"
    )
    (deliverables / "GOAI_VisionDataGate_BoundlessAgents_20260816.pdf").write_bytes(
        b"historical-pdf"
    )
    (deliverables / "VisionDataGate_GOAI_AutoDemo_20260810.mp4").write_bytes(
        b"superseded-video"
    )
    (qa / "video_qa.json").write_text('{"old":true}\n', encoding="utf-8")
    (qa / "independent_qa.py").write_text("raise SystemExit\n", encoding="utf-8")
    (qa / "semifinal_rc3_video_contact_sheet_20260831.png").write_bytes(
        b"current-contact-sheet"
    )
    (qa / "semifinal_rc3_video_qa_20260831.json").write_text(
        '{"status":"PASS_LOCAL_VIDEO_QA"}\n', encoding="utf-8"
    )
    docs = source / "docs"
    docs.mkdir()
    (docs / "DEMO_90S_SCRIPT_RC3.md").write_text(
        "# Current 90-second demo\n", encoding="utf-8"
    )
    (current_reports / "FINAL_QA_REPORT_20260812.md").write_text(
        "old report\n", encoding="utf-8"
    )
    (current_reports / "FINAL_QA_REPORT_20260816.md").write_text(
        "current report\n", encoding="utf-8"
    )
    (current_reports / "FINAL_QA_REPORT_20260816.json").write_text(
        '{"status":"PASS"}\n', encoding="utf-8"
    )
    (current_reports / "SUBMISSION_DELIVERY_RECEIPT_20260816.json").write_text(
        '{"status":"PENDING"}\n', encoding="utf-8"
    )
    (current_reports / "API_SMOKE_20260813.json").write_text(
        '{"status":"PASS"}\n', encoding="utf-8"
    )
    (current_reports / "DYNAMICBENCH_V2_WORKER_SELECTION_20260828.json").write_text(
        '{"status":"PASS"}\n', encoding="utf-8"
    )
    (current_reports / "DYNAMICBENCH_V3_REPLANNING_20260829.json").write_text(
        '{"status":"PASS"}\n', encoding="utf-8"
    )
    (current_reports / "DYNAMICBENCH_V4_PRODUCT_RUNTIME_20260829.json").write_text(
        '{"status":"PASS"}\n', encoding="utf-8"
    )
    (current_reports / "dynamic_vs_fixed_exhaustive_paired_comparison.json").write_text(
        '{"status":"PASS"}\n', encoding="utf-8"
    )
    (current_reports / "dynamic_vs_fixed_rule_paired_comparison.json").write_text(
        '{"status":"PASS"}\n', encoding="utf-8"
    )
    (docs / "GOAI_SEMIFINAL_OFFICIAL_FEEDBACK_CLOSURE_20260831.md").write_text(
        "# Redacted official feedback closure\n", encoding="utf-8"
    )
    (current_reports / "README.md").write_text(
        "Current decision: DO_NOT_SUBMIT_RC3\n", encoding="utf-8"
    )

    archive_path = tmp_path / "submission.zip"
    build_deterministic_zip(source, archive_path)

    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
    assert "deliverables/GOAI_VisionDataGate_Semifinal_RC3_20260831.pptx" in names
    assert "deliverables/GOAI_VisionDataGate_Semifinal_RC3_20260831.pdf" in names
    assert "deliverables/VisionDataGate_GOAI_Semifinal_RC3_20260831.mp4" in names
    assert "deliverables/_qa/semifinal_rc3_video_contact_sheet_20260831.png" in names
    assert "deliverables/_qa/semifinal_rc3_video_qa_20260831.json" in names
    assert "docs/DEMO_90S_SCRIPT_RC3.md" in names
    assert "deliverables/GOAI_VisionDataGate_BoundlessAgents_20260816.pptx" not in names
    assert "deliverables/GOAI_VisionDataGate_BoundlessAgents_20260816.pdf" not in names
    assert "10_reports/FINAL_QA_REPORT_20260816.md" not in names
    assert "10_reports/FINAL_QA_REPORT_20260816.json" not in names
    assert "10_reports/SUBMISSION_DELIVERY_RECEIPT_20260816.json" not in names
    assert "10_reports/API_SMOKE_20260813.json" not in names
    assert "10_reports/DYNAMICBENCH_V2_WORKER_SELECTION_20260828.json" in names
    assert "10_reports/DYNAMICBENCH_V3_REPLANNING_20260829.json" in names
    assert "10_reports/DYNAMICBENCH_V4_PRODUCT_RUNTIME_20260829.json" in names
    assert "10_reports/dynamic_vs_fixed_exhaustive_paired_comparison.json" in names
    assert "10_reports/dynamic_vs_fixed_rule_paired_comparison.json" in names
    assert "docs/GOAI_SEMIFINAL_OFFICIAL_FEEDBACK_CLOSURE_20260831.md" in names
    assert "10_reports/README.md" not in names
    assert "deliverables/VisionDataGate_GOAI_AutoDemo_20260810.mp4" not in names
    assert "deliverables/_qa/video_qa.json" not in names
    assert "deliverables/_qa/independent_qa.py" not in names
    assert "10_reports/FINAL_QA_REPORT_20260812.md" not in names


def test_builder_excludes_all_historical_reviewer_suites(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    old = source / "07_results" / "reviewer_scenario_suite_20260812"
    superseded_v2 = source / "07_results" / "reviewer_scenario_suite_20260812_v2"
    current = source / "07_results" / "reviewer_scenario_suite_20260812_v3"
    old.mkdir(parents=True)
    superseded_v2.mkdir(parents=True)
    current.mkdir(parents=True)
    (source / "README.md").write_text("# safe\n", encoding="utf-8")
    (old / "scenario.json").write_text('{"old":true}\n', encoding="utf-8")
    (superseded_v2 / "scenario.json").write_text('{"v2":true}\n', encoding="utf-8")
    (current / "scenario.json").write_text('{"current":true}\n', encoding="utf-8")

    archive_path = tmp_path / "submission.zip"
    build_deterministic_zip(source, archive_path)

    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
    assert "07_results/reviewer_scenario_suite_20260812/scenario.json" not in names
    assert "07_results/reviewer_scenario_suite_20260812_v2/scenario.json" not in names
    assert "07_results/reviewer_scenario_suite_20260812_v3/scenario.json" not in names


def test_builder_excludes_rc1_evidence_but_keeps_current_rc3_index(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    rc1 = source / "evidence" / "submission" / "vdg-20260816-rc1"
    rc3 = source / "evidence" / "submission" / "vdg-20260831-rc3"
    rc1.mkdir(parents=True)
    rc3.mkdir(parents=True)
    (rc1 / "release_manifest.json").write_text(
        '{"historical":true}\n', encoding="utf-8"
    )
    (rc3 / "evidence_index.json").write_text(
        '{"release_state":"HOLD_AS_RELEASE_TREE"}\n',
        encoding="utf-8",
    )
    (rc3 / "private_receipt.json").write_text(
        '{"public_export_allowed":false}\n',
        encoding="utf-8",
    )
    for relative in CURRENT_GOAL3_PUBLIC_EVIDENCE_PATHS:
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"public-goal3-evidence")
    raw_negative = source / "output" / "semifinal_demo" / "raw_receipt.json"
    raw_negative.parent.mkdir(parents=True)
    raw_negative.write_text(
        '{"browser_stderr":"wrong_secret","public_export_allowed":false}\n',
        encoding="utf-8",
    )

    archive_path = tmp_path / "submission.zip"
    build_deterministic_zip(source, archive_path)

    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
    assert "evidence/submission/vdg-20260816-rc1/release_manifest.json" not in names
    assert "evidence/submission/vdg-20260831-rc3/evidence_index.json" in names
    assert "evidence/submission/vdg-20260831-rc3/private_receipt.json" not in names
    assert set(CURRENT_GOAL3_PUBLIC_EVIDENCE_PATHS) <= names
    assert "output/semifinal_demo/raw_receipt.json" not in names


def test_builder_excludes_stale_rc3_runtime_performance_snapshot(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    docs = source / "docs"
    docs.mkdir(parents=True)
    (source / "README.md").write_text("# safe\n", encoding="utf-8")
    stale_paths = [
        docs / "AGENT_EVALUATION_TOOLS_20260823.md",
        docs / "LONGCAT_AGENT_RESEARCH.md",
        docs / "RC3_RUNTIME_PERFORMANCE_AUDIT_20260828.md",
    ]
    for stale in stale_paths:
        stale.write_text(
            "release_state=NOT_FROZEN\nDO_NOT_SUBMIT_RC3\n",
            encoding="utf-8",
        )

    archive_path = tmp_path / "submission.zip"
    build_deterministic_zip(source, archive_path)

    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
    assert all(path.relative_to(source).as_posix() not in names for path in stale_paths)


def test_builder_excludes_historical_ui_screenshots(tmp_path: Path) -> None:
    source = tmp_path / "source"
    historical = source / "09_assets" / "ui_qa_frozen_20260809"
    historical.mkdir(parents=True)
    (source / "README.md").write_text("# safe\n", encoding="utf-8")
    (historical / "ready-1920x1080.png").write_bytes(b"old-ui")
    (historical / "ui_visual_qa.json").write_text(
        '{"status":"historical"}\n', encoding="utf-8"
    )

    archive_path = tmp_path / "submission.zip"
    build_deterministic_zip(source, archive_path)

    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
    assert "README.md" in names
    assert not any(name.startswith("09_assets/ui_qa_frozen_") for name in names)


def test_default_required_paths_cover_final_submission_anchors() -> None:
    required = set(DEFAULT_SUBMISSION_REQUIRED_PATHS)
    stale_track_docs = {
        "docs/AGENT_EVALUATION_TOOLS_20260823.md",
        "docs/GOAI_live_alignment_20260810.md",
        "docs/GOAI_material_alignment_20260812.md",
        "docs/GOAI_REVIEWER_FEEDBACK_AUDIT_20260812.md",
        "docs/LONGCAT_AGENT_RESEARCH.md",
        "docs/RC3_RUNTIME_PERFORMANCE_AUDIT_20260828.md",
    }
    expected = {
        ".env.example",
        "LICENSE",
        "NOTICE",
        "README.md",
        "pyproject.toml",
        "uv.lock",
        "src/visiondata_gate/api.py",
        "src/visiondata_gate/capa.py",
        "src/visiondata_gate/incident_interaction.py",
        "src/visiondata_gate/product_service.py",
        "src/visiondata_gate/release_attestation.py",
        "src/visiondata_gate/release_evidence.py",
        "src/visiondata_gate/runtime_safety.py",
        "web/package.json",
        "web/package-lock.json",
        "web/tsconfig.json",
        "web/vite.config.ts",
        "web/src/main.tsx",
        "web/src/App.tsx",
        "web/src/data/api.ts",
        "web/src/components/IncidentReviewProjectionPanel.tsx",
        "web/src/components/IncidentInteractionTimeline.tsx",
        "web/src/pages/CaseWorkbenchPage.tsx",
        "web/src/pages/CapaPage.tsx",
        "web/src-tauri/Cargo.toml",
        "web/src-tauri/Cargo.lock",
        "web/src-tauri/tauri.conf.json",
        "web/src-tauri/capabilities/default.json",
        "web/src-tauri/src/lib.rs",
        "desktop/visiondata_gate_backend.spec",
        "build_windows_installer.ps1",
        "run_semifinal_demo.ps1",
        "run_web.ps1",
        "run_workbench.ps1",
        "tools/import_local_env.ps1",
        "tools/prepare_semifinal_demo.py",
        "tools/verify_semifinal_demo_manifest.py",
        "tests/test_desktop_packaging.py",
        "tests/test_semifinal_demo.py",
        "10_reports/DYNAMICBENCH_V2_WORKER_SELECTION_20260828.json",
        "10_reports/DYNAMICBENCH_V3_REPLANNING_20260829.json",
        "10_reports/DYNAMICBENCH_V4_PRODUCT_RUNTIME_20260829.json",
        "10_reports/dynamic_vs_fixed_exhaustive_paired_comparison.json",
        "10_reports/dynamic_vs_fixed_rule_paired_comparison.json",
        "deliverables/GOAI_VisionDataGate_Semifinal_RC3_20260831.pptx",
        "deliverables/GOAI_VisionDataGate_Semifinal_RC3_20260831.pdf",
        "deliverables/VisionDataGate_GOAI_Semifinal_RC3_20260831.mp4",
        "deliverables/_qa/semifinal_rc3_video_contact_sheet_20260831.png",
        "deliverables/_qa/semifinal_rc3_video_qa_20260831.json",
        "docs/DEMO_90S_SCRIPT_RC3.md",
        "docs/GOAI_SEMIFINAL_OFFICIAL_FEEDBACK_CLOSURE_20260831.md",
        "evidence/submission/vdg-20260831-rc3/README.md",
        "evidence/submission/vdg-20260831-rc3/evidence_index.json",
        "src/visiondata_gate/goal3_public_evidence.py",
        "docs/RUNNING.md",
        "docs/SUBMISSION_CHECKLIST.md",
        "docs/SBOM.cdx.json",
        "docs/THIRD_PARTY_NOTICES.md",
        *CURRENT_GOAL3_PUBLIC_EVIDENCE_PATHS,
    }
    historical = {
        "deliverables/GOAI_VisionDataGate_BoundlessAgents_20260816.pptx",
        "deliverables/GOAI_VisionDataGate_BoundlessAgents_20260816.pdf",
        "07_results/frozen_demo_20260809/evidence/demo_summary.json",
        "evidence/submission/vdg-20260816-rc1/release_manifest.json",
        "10_reports/FINAL_QA_REPORT_20260816.json",
    }

    assert expected <= required
    assert set(CURRENT_GOAL3_PUBLIC_EVIDENCE_PATHS) == set(GOAL3_PUBLIC_REQUIRED_PATHS)
    assert required.isdisjoint(stale_track_docs)
    assert required.isdisjoint(historical)
    project_root = Path(__file__).resolve().parents[1]
    assert all((project_root / path).is_file() for path in expected)


def test_goal3_public_evidence_is_jcs_redacted_and_receipt_bound() -> None:
    project_root = Path(__file__).resolve().parents[1]
    result = verify_goal3_public_evidence(project_root)

    assert result["status"] == "PASS_LOCAL_GOAL3_PUBLIC_EVIDENCE"
    assert result["submission_eligible"] is False
    assert result["json_count"] == 5
    assert result["screenshot_count"] == 7

    public_root = project_root / GOAL3_PUBLIC_ROOT
    json_payloads: dict[str, dict[str, object]] = {}
    combined_json = bytearray()
    for name in GOAL3_PUBLIC_JSON_NAMES:
        path = public_root / name
        raw = path.read_bytes()
        payload = json.loads(raw)
        assert raw == canonical_jcs_bytes(payload)
        assert scan_bytes_for_credentials(path.as_posix(), raw) == []
        assert scan_bytes_for_private_paths(path.as_posix(), raw) == []
        json_payloads[name] = payload
        combined_json.extend(raw)

    lowered = bytes(combined_json).lower()
    for forbidden in (
        b"z:" + b"\\private",
        b"z:" + b"/private",
        b"c:" + b"\\users",
        b"appdata",
        b"program files",
        b"127.0.0.1",
        b"localhost",
        b"ws://",
        b"devtools",
        b"stderr",
        b"wrong_secret",
    ):
        assert forbidden not in lowered

    acceptance = json_payloads["goal3_acceptance_summary.json"]
    assert acceptance["source_scope"] == "SYNTHETIC_FIXTURE_REPLAY_ONLY"
    assert acceptance["boundaries"]["private_omni_data_included"] is False
    assert acceptance["boundaries"]["production_release_allowed"] is False
    assert acceptance["boundaries"]["submission_eligible"] is False
    assert acceptance["status"]["capability"] == "PASS_LOCAL_CAPABILITY"
    assert acceptance["status"]["final_delivery"] == "NOT_A_RELEASE_DECISION"
    assert "not a standalone release decision" in acceptance["claim_boundary"]
    assert "separate isolated synthetic ProductRoot" in acceptance["claim_boundary"]
    assert (
        acceptance["source_sets"]["cross_source_product_root_identity_claimed"] is False
    )
    persistent_source = acceptance["source_sets"]["persistent_product_interaction"]
    isolated_source = acceptance["source_sets"]["isolated_goal1_review_ui"]
    assert persistent_source["kind"] == "PERSISTENT_SEMIFINAL_PRODUCT_ROOT"
    assert isolated_source["kind"] == "SEPARATE_ISOLATED_GOAL1_PRODUCT_ROOT"
    assert isolated_source["positive_and_negative_receipts_same_source"] is True
    assert (
        isolated_source["manifest_file_sha256"]
        != persistent_source["manifest_file_sha256"]
    )
    assert (
        acceptance["raw_sources"]["negative_ui_receipt_file_sha256"]
        == "52dae3529fbe2a141d5db0eb9722cd5998a1b46ba14220a02a81bbf3a06f8848"
    )
    assert (
        acceptance["raw_sources"]["negative_ui_receipt_sha256"]
        == "e609579b2abc20fc80a8c23edc879ba1c29ce6c115ba14e1e6540cd0f8b7a785"
    )

    negative = json_payloads["review_projection_negative_ui_summary.json"]
    assert negative["raw_receipt_packaged"] is False
    assert (
        negative["isolated_source"]["cross_source_product_root_identity_claimed"]
        is False
    )
    assert (
        negative["isolated_source"]["manifest_file_sha256"]
        == isolated_source["manifest_file_sha256"]
    )
    assert negative["source_receipt_file_sha256"] == (
        "52dae3529fbe2a141d5db0eb9722cd5998a1b46ba14220a02a81bbf3a06f8848"
    )
    assert negative["source_receipt_sha256"] == (
        "e609579b2abc20fc80a8c23edc879ba1c29ce6c115ba14e1e6540cd0f8b7a785"
    )
    assert negative["summary"]["passed_scenario_count"] == 5
    assert negative["summary"]["no_page_http_write_methods"] is True
    assert negative["summary"]["runtime_exception_count"] == 0

    assert (
        sha256_bytes((public_root / "screenshots/01-review-main.png").read_bytes())
        == "0789896c95aa5f7a9b1f2b0541138349849408d8e309c986303c33898e109747"
    )

    for name in GOAL3_PUBLIC_SCREENSHOT_NAMES:
        info = inspect_public_png(public_root / name)
        assert info["metadata_chunks_included"] is False
        assert info["width"] in {1366, 1440}
        assert info["height"] == 900


def test_goal3_public_evidence_rejects_false_cross_source_identity(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    source = project_root / GOAL3_PUBLIC_ROOT
    target = tmp_path / GOAL3_PUBLIC_ROOT
    shutil.copytree(source, target)

    acceptance_path = target / "goal3_acceptance_summary.json"
    acceptance = json.loads(acceptance_path.read_bytes())
    source_sets = acceptance["source_sets"]
    source_sets["isolated_goal1_review_ui"]["manifest_file_sha256"] = source_sets[
        "persistent_product_interaction"
    ]["manifest_file_sha256"]
    acceptance_path.write_bytes(canonical_jcs_bytes(acceptance))

    with pytest.raises(
        Goal3PublicEvidenceError,
        match="isolated review UI source falsely matches the persistent ProductRoot",
    ):
        verify_goal3_public_evidence(tmp_path)


def test_goal3_public_manifest_projection_rejects_unknown_fields() -> None:
    manifest = {key: None for key in _SEMIFINAL_SOURCE_MANIFEST_FIELDS}
    manifest["operator_email"] = "operator@example.invalid"

    with pytest.raises(
        Goal3PublicEvidenceError,
        match="field set drifted; public projection requires explicit review",
    ):
        _safe_public_manifest(manifest, source_file_sha256="0" * 64)


def test_builder_blocks_credential_without_echoing_value(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    token = "sk-" + "A" * 24
    (source / "config.txt").write_text(token, encoding="utf-8")

    with pytest.raises(PackageSecurityError) as captured:
        build_deterministic_zip(source, tmp_path / "blocked.zip")
    assert "credential_pattern" in str(captured.value)
    assert token not in str(captured.value)
    assert not (tmp_path / "blocked.zip").exists()


@pytest.mark.parametrize(
    "private_path",
    [
        "C:" + "/" + "Users/example/AppData/Local/private.json",
        "/" + "home/example/private/evidence.json",
        "Z:" + "\\customer-alpha\\line-7\\private.json",
        "\\\\factory-nas\\secret-share\\batch\\private.json",
        "/mnt/c/customer-alpha/line-7/private.json",
        "/srv/customer-alpha/line-7/private.json",
    ],
)
def test_builder_blocks_private_local_path_without_echoing_value(
    tmp_path: Path,
    private_path: str,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text(private_path, encoding="utf-8")

    with pytest.raises(PackageSecurityError) as captured:
        build_deterministic_zip(source, tmp_path / "blocked.zip")
    assert "private_path_pattern" in str(captured.value)
    assert private_path not in str(captured.value)
    assert not (tmp_path / "blocked.zip").exists()


def test_private_path_scan_allows_only_explicit_synthetic_path_markers() -> None:
    synthetic = (
        b"VISIONDATA_LOCAL_SOURCE_ALLOW_ROOTS=E:\\\\authorized-data\\\\visiondata"
    )
    assert scan_bytes_for_private_paths(".env.example", synthetic) == []

    issues = scan_bytes_for_private_paths(
        "docs/config.md",
        b"VISIONDATA_LOCAL_SOURCE_ALLOW_ROOTS=Z:\\customer-alpha\\line-7",
    )
    assert {issue.code for issue in issues} == {"private_path_pattern"}


def test_private_path_scan_uses_decoded_json_path_semantics() -> None:
    relative_command = json.dumps(
        {
            "verification_command": (
                r".venv\Scripts\python.exe -m pytest -q tests/test_proof.py"
            )
        }
    ).encode("utf-8")
    assert scan_bytes_for_private_paths("runtime_audit.json", relative_command) == []

    private_location = json.dumps(
        {"evidence_root": r"\\factory-nas\secret-share\batch\private.json"}
    ).encode("utf-8")
    issues = scan_bytes_for_private_paths("runtime_audit.json", private_location)
    assert {issue.code for issue in issues} == {"private_path_pattern"}
    assert all("factory-nas" not in issue.detail for issue in issues)


def test_audit_rejects_path_traversal(tmp_path: Path) -> None:
    malicious = tmp_path / "traversal.zip"
    _write_deterministic_zip(malicious, {"../escape.txt": b"owned"})

    result = audit_submission_zip(malicious)
    assert not result.ok
    assert "unsafe_path" in {issue.code for issue in result.issues}
    assert not result.clean_extract_verified


@pytest.mark.parametrize(
    "name",
    [
        "README.md:secret",
        "file::$DATA",
        "nested/question?.json",
        "nested/control\x1f.json",
    ],
)
def test_archive_path_rejects_windows_ads_and_invalid_characters(name: str) -> None:
    with pytest.raises(ValueError, match="Windows-invalid"):
        validate_archive_path(name)


def test_audit_detects_credentials_without_returning_secret(tmp_path: Path) -> None:
    token = "gsk_" + "B" * 24
    payload = {"README.md": ("credential: " + token).encode("utf-8")}
    entries = dict(payload)
    entries[MANIFEST_NAME] = _manifest_for(payload)
    archive_path = tmp_path / "credential.zip"
    _write_deterministic_zip(archive_path, entries)

    result = audit_submission_zip(archive_path, required_paths=["README.md"])
    serialized = json.dumps(result.to_dict(), ensure_ascii=False)
    assert not result.ok
    assert "credential_pattern" in {issue.code for issue in result.issues}
    assert token not in serialized


def test_audit_detects_private_local_path_without_returning_value(
    tmp_path: Path,
) -> None:
    private_path = "C:" + "/" + "Users/example/private/evidence.json"
    payload = {"README.md": private_path.encode("utf-8")}
    entries = dict(payload)
    entries[MANIFEST_NAME] = _manifest_for(payload)
    archive_path = tmp_path / "private-path.zip"
    _write_deterministic_zip(archive_path, entries)

    result = audit_submission_zip(archive_path, required_paths=["README.md"])
    serialized = json.dumps(result.to_dict(), ensure_ascii=False)
    assert not result.ok
    assert "private_path_pattern" in {issue.code for issue in result.issues}
    assert private_path not in serialized


def test_audit_detects_manifest_tampering_and_missing_required_file(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("original\n", encoding="utf-8", newline="\n")
    good = tmp_path / "good.zip"
    build_deterministic_zip(source, good)

    with zipfile.ZipFile(good) as archive:
        entries = {info.filename: archive.read(info) for info in archive.infolist()}
    entries["README.md"] = b"tampered\n"
    tampered = tmp_path / "tampered.zip"
    _write_deterministic_zip(tampered, entries)

    result = audit_submission_zip(
        tampered,
        required_paths=["README.md", "docs/required.md"],
    )
    codes = {issue.code for issue in result.issues}
    assert not result.ok
    assert "hash_mismatch" in codes
    assert "missing_required_file" in codes


def test_short_key_like_identifier_does_not_trigger_false_positive(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text(
        "Scanner recognizes the sk- prefix only with a bounded long value.\n",
        encoding="utf-8",
    )

    archive = tmp_path / "safe.zip"
    build_deterministic_zip(source, archive)
    audit = audit_submission_zip(archive, required_paths=["README.md"])
    assert audit.ok, audit.to_dict()
