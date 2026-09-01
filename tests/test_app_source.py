from __future__ import annotations

from pathlib import Path
import zipfile

from PIL import Image
from streamlit.testing.v1 import AppTest

from visiondata_gate.dynamic_benchmark import run_dynamic_benchmark
from visiondata_gate.product_models import (
    AuthorizeLocalSourceRequest,
    CreateProjectRequest,
    CreateTaskRequest,
    CreateUserRequest,
    CreateWorkspaceRequest,
    DataSourceKind,
)
from visiondata_gate.product_service import ProductService


APP = Path(__file__).resolve().parents[1] / "app.py"


def _build_omni_fixture(root: Path) -> tuple[Path, str]:
    release = root / "private-release"
    category = "private-widget"
    images = (
        (f"{category}/train/good/train.png", (32, 32), "RGB"),
        (f"{category}/test/good/test-good.png", (48, 32), "RGB"),
        (f"{category}/test/scratch/test-bad.png", (32, 32), "RGB"),
        (f"{category}/ground_truth/scratch/test-bad.png", (32, 32), "L"),
    )
    for relative, size, mode in images:
        destination = release / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        Image.new(mode, size, color=0).save(destination)
    headers = ["数据集名称", "样本总数", "good(train)", "good(test)", "NG(test)"]
    values = [category, 2, 1, 1, 0]

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
    with zipfile.ZipFile(release / "official.xlsx", "w") as bundle:
        bundle.writestr("xl/worksheets/sheet1.xml", sheet)
    return release, category


def _app(tmp_path: Path, monkeypatch: object) -> AppTest:
    product_root = tmp_path / "product"
    monkeypatch.setenv("VISIONDATA_UI_PRODUCT_ROOT", str(product_root))
    return AppTest.from_file(str(APP), default_timeout=30).run()


def test_app_opens_as_product_workspace_without_chat_or_render_side_effects(
    tmp_path: Path, monkeypatch: object
) -> None:
    at = _app(tmp_path, monkeypatch)
    assert not at.exception
    assert len(at.chat_input) == 0
    assert at.radio(key="nav_section").value == "工作台"
    assert at.selectbox(key="active_user_id").value == "usr_local_demo"
    assert at.selectbox(key="active_workspace_id").value == "wsp_local_demo"
    assert at.button(key="FormSubmitter:create_task_form-创建并运行审核任务")
    assert list((tmp_path / "product" / "runs").glob("**/*")) == []


def test_app_accepts_ascii_reviewer_launch_contract(
    tmp_path: Path, monkeypatch: object
) -> None:
    monkeypatch.setenv("VISIONDATA_UI_INITIAL_PAGE", "reviewer")
    at = _app(tmp_path, monkeypatch)
    assert not at.exception
    assert at.radio(key="nav_section").value == "评审模式"
    markdown = "\n".join(item.value for item in at.markdown)
    assert "换型后视觉异常处置与方案复验 Agent" in markdown


def test_app_exposes_enterprise_pages_and_trust_boundary(
    tmp_path: Path, monkeypatch: object
) -> None:
    at = _app(tmp_path, monkeypatch)
    navigation = at.radio(key="nav_section")
    assert list(navigation.options) == [
        "工作台",
        "异常处置",
        "评审模式",
        "项目",
        "数据源",
        "审核记录",
        "能力目录",
        "API 接入",
        "安全与权限",
    ]
    navigation.set_value("安全与权限").run()
    assert not at.exception
    rows = at.dataframe[0].value.to_dict(orient="records")
    text = "\n".join(str(value) for row in rows for value in row.values())
    assert "默认仅绑定本机" in text
    assert "生产 IAM" in text
    assert "SHA-256" in text
    markdown = "\n".join(item.value for item in at.markdown)
    assert "mapped_not_connected" in markdown
    assert "生产写回始终需要真实授权主体" in markdown


def test_app_api_page_uses_real_v1_contract(
    tmp_path: Path, monkeypatch: object
) -> None:
    at = _app(tmp_path, monkeypatch)
    at.radio(key="nav_section").set_value("API 接入").run()
    assert not at.exception
    code = "\n".join(item.value for item in at.code)
    assert "POST http://127.0.0.1:8787/v1/tasks" in code
    assert "GET /v1/tasks/{task_id}/trace" in code
    assert "GET /v1/tasks/{task_id}/evidence" in code
    assert "POST /v1/tasks/{task_id}/reverifications" in code
    assert "GET /v1/tasks/{task_id}/lineage" in code
    assert "POST /v1/tasks/{task_id}/annotation-exports/cvat" in code
    assert "GET /v1/tasks/{task_id}/acceptance-scorecard" in code
    assert "POST /v1/tasks/{task_id}/industrial-incidents" in code
    assert "POST /v1/tasks/{task_id}/industrial-incidents/{case_id}/resume" in code
    assert "X-Actor-User-Id" in code
    captions = "\n".join(item.value for item in at.caption)
    assert "账户初始化接口不会随服务公开" in captions


def test_app_exposes_incident_case_loop_without_flat_work_order_wall(
    tmp_path: Path, monkeypatch: object
) -> None:
    at = _app(tmp_path, monkeypatch)
    at.radio(key="nav_section").set_value("异常处置").run()
    assert not at.exception
    captions = "\n".join(item.value for item in at.caption)
    notices = "\n".join(item.value for item in at.info)
    assert "换型后的 NG 异常" in captions
    assert "只接受已经冻结证据的任务" in notices
    source = APP.read_text(encoding="utf-8")
    assert "build_incident_canvas" in source
    assert "一个事件 · 一个责任入口" in source
    assert "不是固定 DAG" in source
    assert "记录具名决定" in source
    assert "创建新案件版本，不覆盖当前证据" in source


def test_app_reviewer_mode_is_application_first_and_evidence_grounded(
    tmp_path: Path, monkeypatch: object
) -> None:
    at = _app(tmp_path, monkeypatch)
    at.radio(key="nav_section").set_value("评审模式").run()
    assert not at.exception
    markdown = "\n".join(item.value for item in at.markdown)
    captions = "\n".join(item.value for item in at.caption)
    assert "LOCAL / ON-PREM" in markdown
    assert "HUMAN-GOVERNED" in markdown
    assert "换型后视觉异常处置与方案复验 Agent" in markdown
    assert "动态增派 3 个 Worker" in markdown
    assert "证据触发 Replan / Worker" in markdown
    assert ">1 / 3<" in markdown
    assert "冻结裁决 · 规则检查 8 / 8" in markdown
    assert ">RECAPTURE<" in markdown
    assert "CASE VERSION TREE" in markdown
    assert "Findings 49 → 33" in markdown
    assert "Human Decision Bar" in markdown
    assert "父子案件演进" in markdown
    assert "让确定性工具结果可见" in markdown
    assert "SHA-256 + dHash / Hamming" in markdown
    assert "接入已有工业栈" in markdown
    assert "ArchBench-v2" in markdown
    assert "多 Agent 必要性未被支持" in markdown
    assert "冻结 RC2 三级证明" in markdown
    assert "当前受控产品 Gate" in markdown
    assert "冻结 RC2 公开快照" in captions
    assert "Synthetic-v3 公开合成夹具" in captions
    assert "已工程实现" in markdown
    assert "已公开数据实跑" in markdown
    assert "下一阶段外部验收" in markdown
    assert "前两层是本 release 已完成并可复验的工程事实" in markdown
    notices = "\n".join(item.value for item in at.info)
    assert "mapped_not_connected" in notices
    assert "180 张固定公开图像" in captions
    assert "不是全量认证" in captions
    assert len(at.dataframe) >= 2
    compatibility_rows = next(
        frame.value.to_dict(orient="records")
        for frame in at.dataframe
        if "能力层" in frame.value.columns
    )
    compatibility_text = "\n".join(
        str(value) for row in compatibility_rows for value in row.values()
    )
    assert "LOCAL_CONTRACT_VALIDATED" in compatibility_text
    assert "PLANNED_NOT_IMPLEMENTED" in compatibility_text
    assert str(APP.parent) not in markdown
    source = APP.read_text(encoding="utf-8")
    assert "build_reviewer_canvas" in source
    assert "agent_eval_intervention_receipt.json" in source
    assert "tool_fault_intervention_receipt.json" in source
    assert "st.iframe(canvas_src, height=470)" in source
    assert "download_scenario_delivery_receipt" in source
    assert "SCENARIO_DELIVERY_FILENAME" in source


def test_app_loads_hash_bound_dynamic_benchmark_without_overclaiming(
    tmp_path: Path, monkeypatch: object
) -> None:
    run = run_dynamic_benchmark(tmp_path / "dynamic-benchmark.json", repeats=1)
    monkeypatch.setenv("VISIONDATA_UI_DYNAMIC_BENCHMARK", str(run.report_path))
    monkeypatch.setenv("VISIONDATA_UI_DYNAMIC_BENCHMARK_SHA256", run.report_sha256)
    at = _app(tmp_path, monkeypatch)
    at.radio(key="nav_section").set_value("评审模式").run()
    assert not at.exception
    markdown = "\n".join(item.value for item in at.markdown)
    captions = "\n".join(item.value for item in at.caption)
    assert "RC3 DynamicBench-v1" in markdown
    assert "单 Agent 与 Dynamic Leader" in markdown
    assert "少做 57 次无效补证" in markdown
    assert "没有快过单 Agent" in markdown
    assert "不是工业模型精度或对未运行竞品的数值领先" in markdown
    assert "actual model calls = 0" in captions
    assert "NOT_CONNECTED" in captions
    assert str(run.report_path) not in markdown


def test_app_fails_closed_on_dynamic_benchmark_sha_mismatch(
    tmp_path: Path, monkeypatch: object
) -> None:
    run = run_dynamic_benchmark(tmp_path / "dynamic-benchmark.json", repeats=1)
    monkeypatch.setenv("VISIONDATA_UI_DYNAMIC_BENCHMARK", str(run.report_path))
    monkeypatch.setenv("VISIONDATA_UI_DYNAMIC_BENCHMARK_SHA256", "0" * 64)
    at = _app(tmp_path, monkeypatch)
    at.radio(key="nav_section").set_value("评审模式").run()
    assert not at.exception
    warnings = "\n".join(item.value for item in at.warning)
    assert "结构、哈希或固定分母校验" in warnings
    assert str(run.report_path) not in warnings


def test_app_presents_three_real_product_entry_points_without_customer_claims(
    tmp_path: Path, monkeypatch: object
) -> None:
    at = _app(tmp_path, monkeypatch)
    markdown = "\n".join(item.value for item in at.markdown)
    assert "团队工作台" in markdown
    assert "企业 Agent 调用" in markdown
    assert "业务系统嵌入" in markdown
    assert "POST /v1/tasks" in markdown
    assert "GET /trace · /evidence" in markdown
    assert "已有企业客户" not in markdown

    at.radio(key="nav_section").set_value("API 接入").run()
    api_markdown = "\n".join(item.value for item in at.markdown)
    assert "202 Accepted" in api_markdown
    assert "GET /tasks · /events" in api_markdown
    assert "ETag · X-Evidence-SHA256" in api_markdown
    assert "整改与回传" in api_markdown


def test_app_exposes_runtime_safety_and_backend_boundaries() -> None:
    source = Path("app.py").read_text(encoding="utf-8")
    assert "model_transport_receipt.json" in source
    assert "prompt_injection_runtime_receipt.json" in source
    assert "backend_identity_runtime_receipt.json" in source
    assert "CONTRACT_CONNECTED_LOCAL_TEST" in source
    assert "REAL_BACKEND_NOT_CONNECTED" in source
    assert "整改与复验运行链" in source
    assert "create_reverification_task" in source
    assert "POST /v1/tasks/{task_id}/capa-cases" in source
    assert "GET /v1/tasks/{task_id}/capa-cases/{case_id}/outcome-assessment" in source
    assert "GET /v1/data-sources/{source_id}/authorization-events" in source
    assert "POST /v1/data-sources/{source_id}/revocations" in source


def test_app_marks_real_evidence_as_unmounted_by_default(
    tmp_path: Path, monkeypatch: object
) -> None:
    monkeypatch.delenv("VISIONDATA_UI_EXTERNAL_GATE_RESULT", raising=False)
    at = _app(tmp_path, monkeypatch)
    assert not at.exception
    markdown = "\n".join(item.value for item in at.markdown)
    assert "受控真实证据未挂载" in markdown
    assert "全量数据认证" not in markdown


def test_app_mounts_only_a_validated_redacted_gate_result(
    tmp_path: Path, monkeypatch: object
) -> None:
    from visiondata_gate.contracts import (
        AgentOpinion,
        CouncilTrace,
        GateResult,
        RuleCheck,
        RuleCheckResult,
        ToolTrace,
    )

    digest = "a" * 64
    result = GateResult(
        run_id="controlled-real-run",
        batch_id="redacted-batch",
        contract_id="redacted-contract",
        input_sha256=digest,
        policy_version="industrial-gate-v1",
        decision="RECAPTURE",
        decision_reason="Fixed sample triggered a frozen threshold.",
        metrics={"sample_count": 180},
        findings=[],
        tool_trace=[
            ToolTrace(
                sequence=1,
                tool="image_quality",
                status="ok",
                input_sha256=digest,
                result_sha256="b" * 64,
            )
        ],
        council_trace=CouncilTrace(
            backend="shared-simulated-backend",
            shared_model_disclosure="One shared simulated AI backend.",
            independent_opinions=[
                AgentOpinion(
                    role_id="ai_quality",
                    display_name="AI Quality Expert",
                    focus="Quality evidence",
                    challenge="Fixed-sample boundary",
                    recommendation="RECAPTURE",
                    confidence_axes={
                        "E": "high",
                        "T": "high",
                        "A": "low",
                        "M": "medium",
                    },
                )
            ],
            cross_examination=[],
            unresolved_objections=[],
        ),
        rule_checks=[
            RuleCheck(
                check_id="RC-TRACE-OK",
                status=RuleCheckResult.PASS,
                detail="The tool trace completed.",
            )
        ],
        work_orders=[],
    )
    gate_path = tmp_path / "redacted-gate-result.json"
    gate_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    monkeypatch.setenv("VISIONDATA_UI_EXTERNAL_GATE_RESULT", str(gate_path))

    at = _app(tmp_path, monkeypatch)
    assert not at.exception
    markdown = "\n".join(item.value for item in at.markdown)
    captions = "\n".join(item.value for item in at.caption)
    assert "真实 Omni 固定样本 Gate" in markdown
    assert "controlled-real-run" not in markdown
    assert str(gate_path) not in markdown
    assert "固定分母" in markdown and ">180<" in markdown
    assert "需要整改" in markdown
    assert "固定样本 Gate" in captions
    assert "全量数据认证" in captions


def test_app_rejects_invalid_external_gate_result(
    tmp_path: Path, monkeypatch: object
) -> None:
    invalid_path = tmp_path / "invalid-gate-result.json"
    invalid_path.write_text('{"decision":"PASS"}', encoding="utf-8")
    monkeypatch.setenv("VISIONDATA_UI_EXTERNAL_GATE_RESULT", str(invalid_path))
    at = _app(tmp_path, monkeypatch)
    assert not at.exception
    warnings = "\n".join(item.value for item in at.warning)
    assert "无法读取或未通过结构校验" in warnings
    assert str(invalid_path) not in warnings


def test_app_external_gate_panel_has_explicit_fixed_sample_boundaries() -> None:
    source = APP.read_text(encoding="utf-8")
    assert "真实 Omni 固定样本 Gate" in source
    assert "不读取或暴露原始图像、类别名、文件名和私有数据路径" in source
    assert "不等同于全量数据认证、模型精度、客户现场、生产部署或生产批准" in source
    assert "GateResult.model_validate_json" in source
    assert "VISIONDATA_UI_EXTERNAL_GATE_RESULT" in source


def test_app_keeps_raw_evidence_identifiers_out_of_business_view() -> None:
    source = APP.read_text(encoding="utf-8")

    assert "vg-evidence-grid" in source
    assert "vg-metrics-grid" in source
    assert "完整 finding ID、evidence_span、" in source
    assert "reason_trace 与规则检查" in source
    assert '"证据片段": row.get("evidence_span", "")' not in source
    assert '"整改任务": row.get("work_order_ids", "")' not in source


def test_app_presents_risk_plans_before_atomic_work_order_ledger() -> None:
    source = APP.read_text(encoding="utf-8")

    assert 'metric("风险处置流"' in source
    assert 'metric("候选整改方案"' in source
    assert 'metric("原子证据记录"' in source
    assert "不等于同数量的 Agent 任务" in source
    assert "#### 三套候选整改方案" in source
    assert "相对工作量只用于本次方案排序，不是工时、金额或成功承诺" in source
    assert "尚未执行；必须人工计划批准并由独立 child Run 按同合同复验" in source
    assert 'metrics[2].metric("可执行工单"' not in source
    assert "整改执行与独立复验" in source
    assert "授权生命周期" in source
    assert "授权事件 SHA" in source
    assert "生成派生版本并执行 child Run" in source
    assert "责任队列" in source


def test_app_data_source_page_fails_closed_without_server_allowlist(
    tmp_path: Path, monkeypatch: object
) -> None:
    monkeypatch.delenv("VISIONDATA_LOCAL_SOURCE_ALLOW_ROOTS", raising=False)
    at = _app(tmp_path, monkeypatch)
    at.radio(key="nav_section").set_value("数据源").run()
    assert not at.exception
    warnings = "\n".join(item.value for item in at.warning)
    markdown = "\n".join(item.value for item in at.markdown)
    assert "授权入口已失败关闭" in warnings
    assert "路径与类别名不在业务界面展示" in markdown
    assert not any(item.label == "服务器本地目录" for item in at.text_input)


def test_app_requires_operator_to_enter_rights_basis_without_prefill(
    tmp_path: Path, monkeypatch: object
) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setenv("VISIONDATA_LOCAL_SOURCE_ALLOW_ROOTS", str(allowed))
    at = _app(tmp_path, monkeypatch)
    at.radio(key="nav_section").set_value("数据源").run()
    assert not at.exception
    rights_basis = next(item for item in at.text_area if item.label == "权利与使用依据")
    assert rights_basis.value == ""
    assert "系统不会代填或推定权利状态" in (rights_basis.placeholder or "")


def test_app_renders_completed_local_omni_task_with_dynamic_evidence(
    tmp_path: Path, monkeypatch: object
) -> None:
    allowed = tmp_path / "allowed"
    release, category = _build_omni_fixture(allowed)
    product_root = tmp_path / "product"
    service = ProductService(
        product_root,
        local_source_allow_roots=[allowed],
        recover_interrupted=False,
    )
    user = service.create_user(CreateUserRequest(display_name="Industrial Operator"))
    workspace = service.create_workspace(
        CreateWorkspaceRequest(name="Industrial Workspace", owner_user_id=user.user_id)
    )
    source = service.authorize_local_source(
        user.user_id,
        AuthorizeLocalSourceRequest(
            workspace_id=workspace.workspace_id,
            display_name="Authorized fixture",
            root_path=str(release),
            source_archive_sha256="7" * 64,
            purpose="Read-only industrial data release gate verification.",
            rights_basis="Authorized local test fixture without raw redistribution.",
            operator_attests_authorized_use=True,
        ),
    )
    project = service.create_project(
        user.user_id,
        CreateProjectRequest(
            workspace_id=workspace.workspace_id,
            name="Local Omni Project",
            source_kind=DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY,
        ),
    )
    task = service.create_task(
        user.user_id,
        CreateTaskRequest(
            project_id=project.project_id,
            goal="Run authorized industrial evidence gate and deliver work orders.",
            source_kind=DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY,
            source_id=source.source_id,
            seed=17,
        ),
        auto_start=False,
    )
    completed = service.run_task_sync(task.task_id)
    service.close(wait=True)
    assert completed.execution_status.value == "COMPLETED"

    monkeypatch.setenv("VISIONDATA_UI_PRODUCT_ROOT", str(product_root))
    monkeypatch.setenv("VISIONDATA_LOCAL_SOURCE_ALLOW_ROOTS", str(allowed))
    at = AppTest.from_file(str(APP), default_timeout=30).run()
    at.selectbox(key="active_user_id").set_value(user.user_id).run()
    at.selectbox(key="active_workspace_id").set_value(workspace.workspace_id).run()
    at.radio(key="nav_section").set_value("审核记录").run()
    assert not at.exception
    markdown = "\n".join(item.value for item in at.markdown)
    captions = "\n".join(item.value for item in at.caption)
    code = "\n".join(item.value for item in at.code)
    assert "本地授权工业数据" in markdown
    assert "元数据总量独立复核" in markdown
    assert "原生分辨率分组复查" in markdown
    assert "跨工具工单冲突裁决" in markdown
    assert "风险处置流" in markdown
    assert "三套候选整改方案" in markdown
    assert "关键风险优先隔离" in markdown
    assert "完整证据闭环" in markdown
    assert "不等于同数量的 Agent 任务" in captions
    assert "Semantic plan SHA-256" in code
    assert str(release) not in markdown
    assert category not in markdown


def test_app_does_not_claim_production_or_legal_approval() -> None:
    source = APP.read_text(encoding="utf-8")
    forbidden = ("已通过产线验收", "已获得企业授权", "法律电子签名", "真人专家已批准")
    assert not any(text in source for text in forbidden)
    assert "st.chat_input" not in source
    assert "赛道适配矩阵" not in source
    assert "API Key（仅本轮内存" not in source
    assert "应用负责进入真实业务流程" not in source
    assert "真实用户 · 真实任务形态" not in source
