from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import zipfile

from PIL import Image
from fastapi.testclient import TestClient
import pytest

import visiondata_gate.product_runs as product_runs
from visiondata_gate.api import create_app
from visiondata_gate.evidence import canonical_json_bytes
from visiondata_gate.product_models import (
    AuthorizeLocalSourceRequest,
    CreateProjectRequest,
    CreateTaskRequest,
    CreateUserRequest,
    CreateWorkspaceRequest,
    DataSourceKind,
    RevokeLocalSourceAuthorizationRequest,
    TaskExecutionStatus,
    TaskInterventionAction,
    TaskInterventionRequest,
)
from visiondata_gate.product_service import ProductService, UnsupportedSourceError
from visiondata_gate.task_store import ConflictError


RULEPACK_SOURCE = (
    Path(__file__).resolve().parents[1] / "rulepacks" / "industrial-v1.json"
)


def _write_metadata(path: Path, *, category: str, total: int) -> None:
    headers = ["数据集名称", "样本总数", "good(train)", "good(test)", "NG(test)"]
    values = [category, total, 1, 1, max(total - 2, 0)]

    def cell(column: str, row: int, value: str | int) -> str:
        if isinstance(value, int):
            return f'<c r="{column}{row}"><v>{value}</v></c>'
        return f'<c r="{column}{row}" t="inlineStr"><is><t>{value}</t></is></c>'

    columns = ["A", "B", "C", "D", "E"]
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData><row r="1">'
        + "".join(
            cell(column, 1, value)
            for column, value in zip(columns, headers, strict=True)
        )
        + '</row><row r="2">'
        + "".join(
            cell(column, 2, value)
            for column, value in zip(columns, values, strict=True)
        )
        + "</row></sheetData></worksheet>"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr("xl/worksheets/sheet1.xml", sheet)


def _build_source(root: Path, *, mixed_resolution: bool = True) -> tuple[Path, str]:
    release = root / "omni-private-release"
    category = "private-widget"
    train = Image.new("RGB", (32, 32), color=(90, 120, 150))
    test_good = Image.new(
        "RGB", (48, 32) if mixed_resolution else (32, 32), color=(90, 120, 150)
    )
    anomaly = Image.new("RGB", (32, 32), color=(90, 120, 150))
    mask = Image.new("L", (32, 32), color=0)
    for relative, payload in (
        (f"{category}/train/good/train.png", train),
        (f"{category}/test/good/test-good.png", test_good),
        (f"{category}/test/scratch/test-bad.png", anomaly),
        (f"{category}/ground_truth/scratch/test-bad.png", mask),
    ):
        destination = release / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload.save(destination)
    _write_metadata(release / "official.xlsx", category=category, total=2)
    return release, category


def _workspace(service: ProductService) -> tuple[str, str]:
    user = service.create_user(CreateUserRequest(display_name="Omni Operator"))
    workspace = service.create_workspace(
        CreateWorkspaceRequest(name="Omni Workspace", owner_user_id=user.user_id)
    )
    return user.user_id, workspace.workspace_id


def _authorization(*, workspace_id: str, release: Path) -> AuthorizeLocalSourceRequest:
    return AuthorizeLocalSourceRequest(
        workspace_id=workspace_id,
        display_name="Omni-AD-30 只读公开子集",
        root_path=str(release),
        source_archive_sha256="7" * 64,
        purpose="用于工业视觉训练数据发布前的本地只读质量门禁验证。",
        rights_basis="公开访问竞赛子集，仅用于本地只读开发验证，不再分发原始数据。",
        operator_attests_authorized_use=True,
    )


def test_local_source_authorization_is_allowlisted_and_path_redacted(
    tmp_path: Path,
) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    service = ProductService(
        tmp_path / "product",
        local_source_allow_roots=[allowed],
        recover_interrupted=False,
    )
    actor, workspace_id = _workspace(service)
    outside_release, _ = _build_source(outside)

    try:
        service.authorize_local_source(
            actor, _authorization(workspace_id=workspace_id, release=outside_release)
        )
    except UnsupportedSourceError:
        pass
    else:
        raise AssertionError("outside source must be rejected")
    assert service.list_local_source_authorizations(actor, workspace_id) == []

    release, category = _build_source(allowed)
    receipt = service.authorize_local_source(
        actor, _authorization(workspace_id=workspace_id, release=release)
    )
    serialized = receipt.model_dump_json()
    assert str(release) not in serialized
    assert category not in serialized
    assert receipt.read_only is True
    assert receipt.raw_redistribution_allowed is False
    assert receipt.data_profile["source_image_count"] == 3
    assert receipt.data_profile["source_mask_count"] == 1
    assert service.health().data_sources["local_authorized_directory"] == (
        "connected_readonly_allowlist"
    )


def test_source_revocation_is_append_only_and_fails_pending_task_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allowed = tmp_path / "allowed"
    release, _ = _build_source(allowed)
    product_root = tmp_path / "product"
    service = ProductService(
        product_root,
        local_source_allow_roots=[allowed],
        recover_interrupted=False,
    )
    actor, workspace_id = _workspace(service)
    source = service.authorize_local_source(
        actor, _authorization(workspace_id=workspace_id, release=release)
    )
    assert source.status == "active"
    assert source.latest_authorization_event_type.value == "GRANTED"
    project = service.create_project(
        actor,
        CreateProjectRequest(
            workspace_id=workspace_id,
            name="Revocation Gate",
            source_kind=DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY,
        ),
    )
    task = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project.project_id,
            goal="验证批准后撤销授权会让旧批准和待运行任务立即失败关闭。",
            source_kind=DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY,
            source_id=source.source_id,
            plan_approval_required=True,
        ),
        auto_start=False,
    )
    monkeypatch.setattr(service, "start_task", lambda task_id: None)
    approval = service.intervene_task(
        actor,
        task.task_id,
        TaskInterventionRequest(
            action=TaskInterventionAction.APPROVE_PLAN,
            note="批准仅绑定当前授权事件；授权变化后不得复用。",
        ),
    )
    assert approval.approval_binding is not None
    assert (
        approval.approval_binding.source_authorization_event_sha256
        == source.latest_authorization_event_sha256
    )

    revoked = service.revoke_local_source_authorization(
        actor,
        source.source_id,
        RevokeLocalSourceAuthorizationRequest(
            reason="操作员撤回该数据源对当前工作区的一切后续只读执行授权。",
            expected_latest_event_sha256=source.latest_authorization_event_sha256,
        ),
    )
    assert revoked.event_type.value == "REVOKED"
    assert revoked.previous_event_sha256 == source.latest_authorization_event_sha256
    assert revoked.fail_closed_task_ids == [task.task_id]
    failed = service.get_task(actor, task.task_id)
    assert failed.execution_status is TaskExecutionStatus.FAILED
    assert failed.error_code == "SOURCE_AUTHORIZATION_REVOKED"
    current = service.get_local_source_authorization(actor, source.source_id)
    assert current.status == "revoked"
    assert current.authorization_event_count == 2
    assert current.latest_authorization_event_sha256 == revoked.event_sha256
    chain = service.list_source_authorization_events(actor, source.source_id)
    assert [item.event_type.value for item in chain] == ["GRANTED", "REVOKED"]

    original_grant = json.loads(
        (
            product_root
            / "source_authorizations"
            / source.source_id
            / "authorization_receipt.json"
        ).read_text(encoding="utf-8")
    )
    assert original_grant["status"] == "active"
    assert original_grant["latest_authorization_event_sha256"] == (
        source.latest_authorization_event_sha256
    )
    event_files = sorted(
        (product_root / "source_authorizations" / source.source_id / "events").glob(
            "*.json"
        )
    )
    assert len(event_files) == 2

    with sqlite3.connect(product_root / "product.sqlite3") as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE source_authorization_events SET reason = 'tampered' "
                "WHERE event_id = ?",
                (revoked.event_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "DELETE FROM source_authorization_events WHERE event_id = ?",
                (revoked.event_id,),
            )


def test_source_expiry_event_fails_pending_task_without_source_read(
    tmp_path: Path,
) -> None:
    allowed = tmp_path / "allowed"
    release, _ = _build_source(allowed)
    service = ProductService(
        tmp_path / "product",
        local_source_allow_roots=[allowed],
        recover_interrupted=False,
    )
    actor, workspace_id = _workspace(service)
    request = _authorization(workspace_id=workspace_id, release=release).model_copy(
        update={"authorization_valid_until": "2999-01-01T00:00:00+00:00"}
    )
    source = service.authorize_local_source(actor, request)
    project = service.create_project(
        actor,
        CreateProjectRequest(
            workspace_id=workspace_id,
            name="Expiry Gate",
            source_kind=DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY,
        ),
    )
    task = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project.project_id,
            goal="验证到期授权在任何数据读取前失败关闭待运行任务。",
            source_kind=DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY,
            source_id=source.source_id,
            plan_approval_required=True,
        ),
        auto_start=False,
    )
    expired = service.store.expire_due_local_source_authorizations(
        now="3000-01-01T00:00:00+00:00"
    )
    assert len(expired) == 1
    assert expired[0].event_type.value == "EXPIRED"
    assert expired[0].fail_closed_task_ids == [task.task_id]
    receipt = service.get_local_source_authorization(actor, source.source_id)
    assert receipt.status == "expired"
    failed = service.get_task(actor, task.task_id)
    assert failed.execution_status is TaskExecutionStatus.FAILED
    assert failed.error_code == "SOURCE_AUTHORIZATION_EXPIRED"


def test_authorized_omni_source_runs_through_product_task_and_evidence_delivery(
    tmp_path: Path,
) -> None:
    allowed = tmp_path / "allowed"
    release, category = _build_source(allowed)
    source_snapshot = sorted(
        (path.relative_to(release).as_posix(), path.stat().st_size)
        for path in release.rglob("*")
        if path.is_file()
    )
    service = ProductService(
        tmp_path / "product",
        local_source_allow_roots=[allowed],
        recover_interrupted=False,
    )
    actor, workspace_id = _workspace(service)
    receipt = service.authorize_local_source(
        actor, _authorization(workspace_id=workspace_id, release=release)
    )
    project = service.create_project(
        actor,
        CreateProjectRequest(
            workspace_id=workspace_id,
            name="真实工业数据门禁",
            source_kind=DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY,
        ),
    )
    task = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project.project_id,
            goal="审核授权的工业视觉数据，动态补证并交付可追溯工单。",
            source_kind=DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY,
            source_id=receipt.source_id,
            seed=17,
        ),
        auto_start=False,
    )
    preflight = service.task_preflight(actor, task.task_id)
    assert preflight.overall_status == "READY_TO_RUN"
    assert preflight.prerequisite_ready is True
    assert preflight.execution_ready is True
    assert preflight.source_profile_status == "MATCHED"
    assert len(preflight.report_sha256) == 64
    assert (
        preflight.report_sha256
        == hashlib.sha256(
            canonical_json_bytes(preflight.model_dump(exclude={"report_sha256"}))
        ).hexdigest()
    )
    completed = service.run_task_sync(task.task_id)

    assert completed.execution_status is TaskExecutionStatus.COMPLETED
    assert completed.source_id == receipt.source_id
    assert completed.initial_decision != "PASS"
    assert completed.final_decision != "PASS"
    assert completed.evidence_sha256
    events = service.list_events(actor, task.task_id)
    assert any(
        json.loads(event.payload_json)["actor"] == "Dynamic Leader" for event in events
    )
    assert any(event.stage == "delivery" for event in events)
    trace = service.read_trace(actor, task.task_id)
    assert trace["intent"] == "authorized_industrial_dataset_release_gate"
    assert trace["tool_call_count"] >= 5
    assert trace["approval_handoff"]["status"] == "pending"
    scorecard = service.acceptance_scorecard(actor, task.task_id)
    assert scorecard.overall_status == "PARTIAL_LOCAL"
    assert scorecard.final_gate_decision == completed.final_decision
    assert scorecard.external_connections["data_source"] == (
        "local_authorized_directory:connected_readonly_operator_attested"
    )
    assert scorecard.external_connections["llm"] == (
        "not_connected_runtime_model_calls_0"
    )
    unavailable = {
        metric.key: metric.status
        for metric in scorecard.metrics
        if metric.key
        in {
            "unsupported_claim_rate",
            "citation_validity",
            "critical_bad_release_rate",
            "task_success",
        }
    }
    assert unavailable == {
        "unsupported_claim_rate": "NOT_MEASURED",
        "citation_validity": "NOT_MEASURED",
        "critical_bad_release_rate": "NOT_MEASURED",
        "task_success": "NOT_MEASURED",
    }
    delivery = service.industrial_delivery_receipt(actor, task.task_id)
    assert delivery.schema_version == "visiondata-gate.industrial-delivery.v3"
    assert delivery.final_decision == completed.final_decision
    assert len(delivery.multi_source_fusion) == 6
    assert delivery.inspection_contract is not None
    assert delivery.inspection_contract.input_contract_bound is True
    assert delivery.inspection_contract.same_contract_child_run_required is True
    assert (
        delivery.inspection_contract.aql_interpretation
        == "PROJECT_DEFINED_QUALITY_CONTRACT_NOT_CERTIFIED_AQL"
    )
    assert delivery.inspection_contract.enforced_tools
    assert all(
        len(value) == 64
        for value in delivery.inspection_contract.tool_parameter_sha256.values()
    )
    assert delivery.evidence_fusion_matrix
    assert (
        delivery.evidence_fusion_matrix_sha256
        == hashlib.sha256(
            canonical_json_bytes(
                [
                    entry.model_dump(mode="json")
                    for entry in delivery.evidence_fusion_matrix
                ]
            )
        ).hexdigest()
    )
    for entry in delivery.evidence_fusion_matrix:
        assert "frozen_policy" in entry.source_kinds
        assert entry.evidence_facts
        if entry.fusion_status == "CROSS_SOURCE_CORROBORATED":
            assert {fact.code for fact in entry.evidence_facts} == {entry.issue_code}
            assert len({fact.source_kind for fact in entry.evidence_facts}) > 1
        assert entry.root_cause_established is False
        assert entry.machine_action_permitted is False
        assert (
            entry.entry_sha256
            == hashlib.sha256(
                canonical_json_bytes(
                    entry.model_dump(mode="json", exclude={"entry_sha256"})
                )
            ).hexdigest()
        )
    assert delivery.dynamic_responses
    assert delivery.dynamic_execution_ledger is not None
    assert (
        delivery.dynamic_execution_ledger.token_budget_status
        == "NOT_APPLICABLE_DETERMINISTIC_WORKERS"
    )
    assert (
        delivery.dynamic_execution_ledger.dependency_semantics
        == "EVIDENCE_REFS_NOT_WORKER_CHAIN"
    )
    assert delivery.dynamic_execution_ledger.within_allocated_budget is True
    assert delivery.batch_triage is not None
    assert [stage.tier for stage in delivery.batch_triage.stages] == [
        "L1",
        "L2",
        "L3",
    ]
    assert delivery.batch_triage.full_source_policy_gate_claimed is False
    assert delivery.batch_triage.throughput_benchmark_claimed is False
    assert (
        delivery.batch_triage.ledger_sha256
        == hashlib.sha256(
            canonical_json_bytes(
                delivery.batch_triage.model_dump(mode="json", exclude={"ledger_sha256"})
            )
        ).hexdigest()
    )
    assert delivery.executable_work_orders
    assert delivery.risk_clusters
    assert len(delivery.remediation_plans) == 3
    assert delivery.production_human_approval_required is True
    assert delivery.production_approval_status == "pending"
    assert delivery.anomaly_model_backend == "NOT_CONNECTED"
    assert all(
        order.machine_action_permitted is False
        and order.evidence_refs
        and order.reason_trace
        for order in delivery.executable_work_orders
    )
    assert sum(
        cluster.atomic_work_order_count for cluster in delivery.risk_clusters
    ) == len(delivery.executable_work_orders)
    for cluster in delivery.risk_clusters:
        assert cluster.machine_action_permitted is False
        assert (
            cluster.cluster_sha256
            == hashlib.sha256(
                canonical_json_bytes(
                    cluster.model_dump(mode="json", exclude={"cluster_sha256"})
                )
            ).hexdigest()
        )
    full_plan = next(
        plan
        for plan in delivery.remediation_plans
        if plan.strategy == "full_evidence_closure"
    )
    assert full_plan.evidence_coverage_ratio == 1.0
    assert full_plan.deferred_work_order_ids == []
    assert full_plan.production_release_allowed is False
    assert full_plan.same_contract_child_run_required is True
    assert full_plan.waves[-1].work_order_ids == []
    assert "child Run" in full_plan.waves[-1].objective
    for plan in delivery.remediation_plans:
        assert (
            plan.plan_sha256
            == hashlib.sha256(
                canonical_json_bytes(
                    plan.model_dump(mode="json", exclude={"plan_sha256"})
                )
            ).hexdigest()
        )

    with zipfile.ZipFile(service.evidence_path(actor, task.task_id)) as archive:
        names = set(archive.namelist())
        assert {
            "agent_runtime_trace.json",
            "local_source_authorization_receipt.json",
            "source_profile.json",
            "initial/gate_result.json",
            "final/gate_result.json",
            "dynamic_leader_plan.json",
            "task_summary.json",
            "task_plan_preview.json",
            "task_intervention_timeline.json",
            "industrial_delivery_receipt.json",
        } <= names
        frozen_gate = json.loads(archive.read("final/gate_result.json"))
        default_leader_plan = json.loads(archive.read("dynamic_leader_plan.json"))
        default_gate_receipt = json.loads(archive.read("omni_gate_receipt.json"))
        serialized = "\n".join(
            archive.read(name).decode("utf-8", errors="ignore")
            for name in names
            if name.endswith((".json", ".csv"))
        )
    assert default_leader_plan["rule_pack_runtime_status"] == "NOT_CONFIGURED"
    assert default_leader_plan["rule_pack_source_sha256"] is None
    assert default_gate_receipt["rule_pack_runtime_status"] == "NOT_CONFIGURED"
    assert default_gate_receipt["rule_pack_source_sha256"] is None
    assert default_gate_receipt["rule_pack_binding_sha256"] is None
    source_finding_by_order = {
        item["work_order_id"]: item["replacement_requirements"]["source_finding_id"]
        for item in frozen_gate["work_orders"]
    }
    assert all(
        [span.finding_id for span in item.evidence_span]
        == [source_finding_by_order[item.work_order_id]]
        for item in delivery.executable_work_orders
    )
    assert str(release) not in serialized
    assert category not in serialized
    assert ".png" not in serialized
    assert source_snapshot == sorted(
        (path.relative_to(release).as_posix(), path.stat().st_size)
        for path in release.rglob("*")
        if path.is_file()
    )
    release_readiness = service.task_release_readiness(actor, task.task_id)
    assert release_readiness.overall_status == "BLOCKED_GATE_DECISION"
    assert release_readiness.source_freshness == "CURRENT"
    assert release_readiness.evidence_integrity == "VERIFIED"
    assert release_readiness.open_work_order_count
    assert release_readiness.production_release_allowed is False
    assert (
        release_readiness.report_sha256
        == hashlib.sha256(
            canonical_json_bytes(
                release_readiness.model_dump(exclude={"report_sha256"})
            )
        ).hexdigest()
    )
    assert str(release) not in release_readiness.model_dump_json()
    assert category not in release_readiness.model_dump_json()

    changed_after_run = release / category / "train" / "good" / "post-run.png"
    Image.new("RGB", (32, 32), color=(4, 5, 6)).save(changed_after_run)
    stale = service.task_release_readiness(actor, task.task_id)
    assert stale.overall_status == "BLOCKED_SOURCE_STALE"
    assert stale.source_freshness == "STALE"
    assert stale.current_source_profile_sha256 != stale.frozen_source_profile_sha256
    assert stale.report_sha256 != release_readiness.report_sha256


def test_product_service_activates_explicit_omni_rulepack_in_real_task(
    tmp_path: Path,
) -> None:
    allowed = tmp_path / "allowed"
    release, _ = _build_source(allowed)
    rulepack_path = tmp_path / "reviewed-rulepack.json"
    rulepack_path.write_bytes(RULEPACK_SOURCE.read_bytes())
    expected_sha256 = hashlib.sha256(rulepack_path.read_bytes()).hexdigest()
    service = ProductService(
        tmp_path / "product",
        local_source_allow_roots=[allowed],
        omni_rulepack_path=rulepack_path,
        recover_interrupted=False,
    )
    assert service.omni_rulepack_path == rulepack_path.resolve(strict=True)
    assert service.omni_rulepack_source_sha256 == expected_sha256
    actor, workspace_id = _workspace(service)
    source = service.authorize_local_source(
        actor, _authorization(workspace_id=workspace_id, release=release)
    )
    project = service.create_project(
        actor,
        CreateProjectRequest(
            workspace_id=workspace_id,
            name="Rule Pack Main Chain",
            source_kind=DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY,
        ),
    )
    task = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project.project_id,
            goal="验证显式审核规则包进入 ProductService 的真实 Omni 任务。",
            source_kind=DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY,
            source_id=source.source_id,
            seed=17,
        ),
        auto_start=False,
    )

    completed = service.run_task_sync(task.task_id)

    assert completed.execution_status is TaskExecutionStatus.COMPLETED
    with zipfile.ZipFile(service.evidence_path(actor, task.task_id)) as archive:
        leader_plan = json.loads(archive.read("dynamic_leader_plan.json"))
        gate_receipt = json.loads(archive.read("omni_gate_receipt.json"))
    assert leader_plan["rule_pack_runtime_status"] == "ACTIVATED"
    assert leader_plan["rule_pack_source_sha256"] == expected_sha256
    binding = leader_plan["rule_pack_binding"]
    assert binding["source_sha256"] == expected_sha256
    assert gate_receipt["rule_pack_runtime_status"] == "ACTIVATED"
    assert gate_receipt["rule_pack_source_sha256"] == expected_sha256
    assert gate_receipt["rule_pack_binding_sha256"] == binding["binding_sha256"]


def test_product_service_rejects_omni_rulepack_drift_before_task_execution(
    tmp_path: Path,
) -> None:
    allowed = tmp_path / "allowed"
    release, _ = _build_source(allowed)
    rulepack_path = tmp_path / "reviewed-rulepack.json"
    rulepack_path.write_bytes(RULEPACK_SOURCE.read_bytes())
    service = ProductService(
        tmp_path / "product",
        local_source_allow_roots=[allowed],
        omni_rulepack_path=rulepack_path,
        recover_interrupted=False,
    )
    actor, workspace_id = _workspace(service)
    source = service.authorize_local_source(
        actor, _authorization(workspace_id=workspace_id, release=release)
    )
    project = service.create_project(
        actor,
        CreateProjectRequest(
            workspace_id=workspace_id,
            name="Rule Pack Drift Gate",
            source_kind=DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY,
        ),
    )
    task = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project.project_id,
            goal="规则包在服务初始化后漂移时必须失败关闭。",
            source_kind=DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY,
            source_id=source.source_id,
        ),
        auto_start=False,
    )
    rulepack_path.write_bytes(rulepack_path.read_bytes() + b"\n")

    failed = service.run_task_sync(task.task_id)

    assert failed.execution_status is TaskExecutionStatus.FAILED
    assert failed.error_code == "RulePackDriftError"
    assert "changed after service initialization" in (failed.error_message or "")
    assert failed.evidence_sha256 is None


def test_product_service_rejects_omni_rulepack_drift_during_task_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allowed = tmp_path / "allowed"
    release, _ = _build_source(allowed)
    rulepack_path = tmp_path / "reviewed-rulepack.json"
    rulepack_path.write_bytes(RULEPACK_SOURCE.read_bytes())
    service = ProductService(
        tmp_path / "product",
        local_source_allow_roots=[allowed],
        omni_rulepack_path=rulepack_path,
        recover_interrupted=False,
    )
    actor, workspace_id = _workspace(service)
    source = service.authorize_local_source(
        actor, _authorization(workspace_id=workspace_id, release=release)
    )
    project = service.create_project(
        actor,
        CreateProjectRequest(
            workspace_id=workspace_id,
            name="Rule Pack TOCTOU Gate",
            source_kind=DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY,
        ),
    )
    task = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project.project_id,
            goal="规则包在检查与证据封存之间漂移时必须失败关闭。",
            source_kind=DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY,
            source_id=source.source_id,
        ),
        auto_start=False,
    )
    original_gate = product_runs.run_omni_readonly_gate

    def drift_after_gate(*args, **kwargs):
        run = original_gate(*args, **kwargs)
        rulepack_path.write_bytes(rulepack_path.read_bytes() + b"\n")
        return run

    monkeypatch.setattr(product_runs, "run_omni_readonly_gate", drift_after_gate)

    failed = service.run_task_sync(task.task_id)

    assert failed.execution_status is TaskExecutionStatus.FAILED
    assert failed.error_code == "ValueError"
    assert "drifted during ProductService task execution" in (
        failed.error_message or ""
    )
    assert failed.evidence_sha256 is None


def test_default_api_service_reads_optional_omni_rulepack_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rulepack_path = tmp_path / "api-rulepack.json"
    rulepack_path.write_bytes(RULEPACK_SOURCE.read_bytes())
    monkeypatch.setenv("VISIONDATA_PRODUCT_ROOT", str(tmp_path / "api-product"))
    monkeypatch.setenv("VISIONDATA_OMNI_RULEPACK_PATH", str(rulepack_path))

    app = create_app(ensure_demo_tenant=False)
    service = app.state.product_service

    assert service.omni_rulepack_path == rulepack_path.resolve(strict=True)
    assert (
        service.omni_rulepack_source_sha256
        == hashlib.sha256(rulepack_path.read_bytes()).hexdigest()
    )
    service.close(wait=True)


def test_source_profile_drift_fails_before_real_task_execution(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    release, category = _build_source(allowed)
    service = ProductService(
        tmp_path / "product",
        local_source_allow_roots=[allowed],
        recover_interrupted=False,
    )
    actor, workspace_id = _workspace(service)
    receipt = service.authorize_local_source(
        actor, _authorization(workspace_id=workspace_id, release=release)
    )
    project = service.create_project(
        actor,
        CreateProjectRequest(
            workspace_id=workspace_id,
            name="Drift Gate",
            source_kind=DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY,
        ),
    )
    changed = release / category / "train" / "good" / "changed.png"
    Image.new("RGB", (32, 32), color=(1, 2, 3)).save(changed)
    approval_task = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project.project_id,
            goal="源数据漂移时必须在批准计划前安全阻断。",
            source_kind=DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY,
            source_id=receipt.source_id,
            plan_approval_required=True,
        ),
        auto_start=False,
    )
    preflight = service.task_preflight(actor, approval_task.task_id)
    assert preflight.overall_status == "BLOCKED"
    assert preflight.prerequisite_ready is False
    assert preflight.source_profile_status == "CHANGED"
    with pytest.raises(ConflictError, match="preflight prerequisites are blocked"):
        service.intervene_task(
            actor,
            approval_task.task_id,
            TaskInterventionRequest(
                action=TaskInterventionAction.APPROVE_PLAN,
                note="来源已经变化，不应允许批准运行。",
            ),
        )
    assert service.list_interventions(actor, approval_task.task_id) == []
    assert service.get_task(actor, approval_task.task_id).execution_status is (
        TaskExecutionStatus.PLANNED
    )

    task = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project.project_id,
            goal="源数据漂移时必须在读取任务前安全失败。",
            source_kind=DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY,
            source_id=receipt.source_id,
        ),
        auto_start=False,
    )
    failed = service.run_task_sync(task.task_id)
    assert failed.execution_status is TaskExecutionStatus.FAILED
    assert failed.error_code == "UnsupportedSourceError"
    assert failed.evidence_sha256 is None


def test_approved_plan_becomes_stale_when_local_source_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allowed = tmp_path / "allowed"
    release, category = _build_source(allowed)
    service = ProductService(
        tmp_path / "product",
        local_source_allow_roots=[allowed],
        recover_interrupted=False,
    )
    actor, workspace_id = _workspace(service)
    receipt = service.authorize_local_source(
        actor, _authorization(workspace_id=workspace_id, release=release)
    )
    project = service.create_project(
        actor,
        CreateProjectRequest(
            workspace_id=workspace_id,
            name="Approval Drift Gate",
            source_kind=DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY,
        ),
    )
    task = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project.project_id,
            goal="批准必须同时绑定任务、计划、规则合同与来源画像。",
            source_kind=DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY,
            source_id=receipt.source_id,
            plan_approval_required=True,
        ),
        auto_start=False,
    )
    monkeypatch.setattr(service, "start_task", lambda task_id: None)
    approval = service.intervene_task(
        actor,
        task.task_id,
        TaskInterventionRequest(
            action=TaskInterventionAction.APPROVE_PLAN,
            note="已核对当前来源画像、只读范围与规则合同。",
        ),
    )
    assert approval.approval_binding is not None
    assert approval.approval_binding.source_profile_status == "MATCHED"
    assert approval.approval_binding.source_profile_sha256 is not None
    assert (
        approval.approval_binding.binding_sha256
        == hashlib.sha256(
            canonical_json_bytes(
                approval.approval_binding.model_dump(
                    mode="json", exclude={"binding_sha256"}
                )
            )
        ).hexdigest()
    )

    changed = release / category / "train" / "good" / "after-approval.png"
    Image.new("RGB", (32, 32), color=(8, 9, 10)).save(changed)
    stale = service.task_preflight(actor, task.task_id)
    assert stale.overall_status == "BLOCKED"
    assert stale.execution_ready is False
    assert stale.source_profile_status == "CHANGED"
    approval_check = next(
        item for item in stale.checks if item.key == "human_plan_approval"
    )
    assert approval_check.status == "BLOCKED"
    assert "失效" in approval_check.summary
    with pytest.raises(
        ConflictError,
        match="approval is required and must be current before execution",
    ):
        service.run_task_sync(task.task_id)
    assert service.get_task(actor, task.task_id).execution_status is (
        TaskExecutionStatus.PLANNED
    )


def test_api_exposes_redacted_source_to_real_task_closed_loop(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    release, category = _build_source(allowed)
    service = ProductService(
        tmp_path / "product",
        local_source_allow_roots=[allowed],
        recover_interrupted=False,
    )
    actor, workspace_id = _workspace(service)
    client = TestClient(create_app(service, ensure_demo_tenant=False))
    headers = {"X-Actor-User-Id": actor}

    source_response = client.post(
        "/v1/data-sources/local-authorizations",
        headers=headers,
        json=_authorization(workspace_id=workspace_id, release=release).model_dump(
            mode="json"
        ),
    )
    assert source_response.status_code == 201
    source = source_response.json()
    assert str(release) not in source_response.text
    assert category not in source_response.text
    listed = client.get(
        "/v1/data-sources",
        headers=headers,
        params={"workspace_id": workspace_id},
    )
    assert listed.status_code == 200
    assert [item["source_id"] for item in listed.json()] == [source["source_id"]]

    project_response = client.post(
        "/v1/projects",
        headers=headers,
        json={
            "workspace_id": workspace_id,
            "name": "API Omni Gate",
            "source_kind": "local_authorized_directory",
        },
    )
    assert project_response.status_code == 201
    planned_response = client.post(
        "/v1/tasks",
        headers={**headers, "Idempotency-Key": "omni-api-preflight-v1"},
        json={
            "project_id": project_response.json()["project_id"],
            "goal": "先检查授权快照、工具权限与人工批准边界，再决定是否运行。",
            "source_kind": "local_authorized_directory",
            "source_id": source["source_id"],
            "seed": 17,
            "plan_approval_required": True,
        },
    )
    assert planned_response.status_code == 202
    preflight_response = client.get(
        f"/v1/tasks/{planned_response.json()['task_id']}/preflight",
        headers=headers,
    )
    assert preflight_response.status_code == 200
    assert preflight_response.json()["overall_status"] == "AWAITING_HUMAN_APPROVAL"
    assert preflight_response.json()["prerequisite_ready"] is True

    task_response = client.post(
        "/v1/tasks",
        headers={**headers, "Idempotency-Key": "omni-api-fixture-v1"},
        json={
            "project_id": project_response.json()["project_id"],
            "goal": "通过 API 对授权工业数据执行补证、裁决和证据交付。",
            "source_kind": "local_authorized_directory",
            "source_id": source["source_id"],
            "seed": 17,
        },
    )
    assert task_response.status_code == 202
    task_id = task_response.json()["task_id"]
    service.close(wait=True)
    completed = client.get(f"/v1/tasks/{task_id}", headers=headers)
    assert completed.status_code == 200
    assert completed.json()["execution_status"] == "COMPLETED"
    evidence = client.get(f"/v1/tasks/{task_id}/evidence", headers=headers)
    assert evidence.status_code == 200
    assert len(evidence.headers["x-evidence-sha256"]) == 64
    scorecard = client.get(f"/v1/tasks/{task_id}/acceptance-scorecard", headers=headers)
    assert scorecard.status_code == 200
    payload = scorecard.json()
    assert payload["overall_status"] == "PARTIAL_LOCAL"
    assert payload["external_connections"]["data_source"] == (
        "local_authorized_directory:connected_readonly_operator_attested"
    )
    delivery = client.get(f"/v1/tasks/{task_id}/industrial-delivery", headers=headers)
    assert delivery.status_code == 200
    assert len(delivery.headers["x-content-sha256"]) == 64
    assert delivery.headers["etag"] == f'"{delivery.headers["x-content-sha256"]}"'
    assert delivery.headers["cache-control"] == "private, no-store"
    assert delivery.json()["production_approval_status"] == "pending"
    assert delivery.json()["anomaly_model_backend"] == "NOT_CONNECTED"
    readiness = client.get(f"/v1/tasks/{task_id}/release-readiness", headers=headers)
    assert readiness.status_code == 200
    assert readiness.json()["source_freshness"] == "CURRENT"
    assert readiness.json()["evidence_integrity"] == "VERIFIED"
    assert readiness.json()["production_release_allowed"] is False


def test_api_exposes_hash_bound_source_revocation_without_local_path(
    tmp_path: Path,
) -> None:
    allowed = tmp_path / "allowed"
    release, category = _build_source(allowed)
    service = ProductService(
        tmp_path / "product",
        local_source_allow_roots=[allowed],
        recover_interrupted=False,
    )
    actor, workspace_id = _workspace(service)
    client = TestClient(create_app(service, ensure_demo_tenant=False))
    headers = {"X-Actor-User-Id": actor}
    created = client.post(
        "/v1/data-sources/local-authorizations",
        headers=headers,
        json=_authorization(workspace_id=workspace_id, release=release).model_dump(
            mode="json"
        ),
    )
    assert created.status_code == 201
    source = created.json()
    source_id = source["source_id"]
    events_before = client.get(
        f"/v1/data-sources/{source_id}/authorization-events", headers=headers
    )
    assert events_before.status_code == 200
    assert [item["event_type"] for item in events_before.json()] == ["GRANTED"]
    revoked = client.post(
        f"/v1/data-sources/{source_id}/revocations",
        headers=headers,
        json={
            "reason": "API 操作员撤回该来源在此工作区的后续执行授权。",
            "expected_latest_event_sha256": source["latest_authorization_event_sha256"],
        },
    )
    assert revoked.status_code == 201
    assert revoked.json()["event_type"] == "REVOKED"
    assert str(release) not in revoked.text
    assert category not in revoked.text
    current = client.get(f"/v1/data-sources/{source_id}", headers=headers)
    assert current.status_code == 200
    assert current.json()["status"] == "revoked"
    stale_replay = client.post(
        f"/v1/data-sources/{source_id}/revocations",
        headers=headers,
        json={
            "reason": "用旧哈希重复撤销必须失败关闭，不能伪造第二条撤销。",
            "expected_latest_event_sha256": source["latest_authorization_event_sha256"],
        },
    )
    assert stale_replay.status_code == 409
