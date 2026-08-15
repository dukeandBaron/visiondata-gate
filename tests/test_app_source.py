from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


APP = Path(__file__).resolve().parents[1] / "app.py"


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


def test_app_exposes_enterprise_pages_and_trust_boundary(
    tmp_path: Path, monkeypatch: object
) -> None:
    at = _app(tmp_path, monkeypatch)
    navigation = at.radio(key="nav_section")
    assert list(navigation.options) == [
        "工作台",
        "评审模式",
        "项目",
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
    assert "X-Actor-User-Id" in code
    captions = "\n".join(item.value for item in at.caption)
    assert "账户初始化接口不会随服务公开" in captions


def test_app_reviewer_mode_is_application_first_and_evidence_grounded(
    tmp_path: Path, monkeypatch: object
) -> None:
    at = _app(tmp_path, monkeypatch)
    at.radio(key="nav_section").set_value("评审模式").run()
    assert not at.exception
    markdown = "\n".join(item.value for item in at.markdown)
    captions = "\n".join(item.value for item in at.caption)
    assert "赛道二 · 无界应用" in markdown
    assert "AI+工业制造" in markdown
    assert "工业视觉数据治理与发布 Agent" in markdown
    assert "动态增派 3 个 Worker" in markdown
    assert "重规划 / 动态 Worker" in markdown
    assert ">1 / 3<" in markdown
    assert "批次结论 · 规则检查 8 / 8" in markdown
    assert ">RECAPTURE<" in markdown
    assert "ArchBench-v2" in markdown
    assert "多 Agent 必要性未被支持" in markdown
    assert "场景落地证明：我们已经做到哪一层" in markdown
    assert "已工程实现" in markdown
    assert "已公开数据实跑" in markdown
    assert "下一阶段外部验收" in markdown
    assert "前两层是本 release 已完成并可复验的工程事实" in markdown
    notices = "\n".join(item.value for item in at.info)
    assert "mapped_not_connected" in notices
    assert "180 张固定公开图像" in captions
    assert "全量 Gate 认证" in captions
    assert len(at.dataframe) == 2
    assert str(APP.parent) not in markdown
    source = APP.read_text(encoding="utf-8")
    assert "build_reviewer_canvas" in source
    assert "st.iframe(canvas_src, height=470)" in source
    assert "download_scenario_delivery_receipt" in source
    assert "SCENARIO_DELIVERY_FILENAME" in source


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
    assert "完整 finding ID、evidence_span、reason_trace" in source
    assert '"证据片段": row.get("evidence_span", "")' not in source
    assert '"整改任务": row.get("work_order_ids", "")' not in source


def test_app_does_not_claim_production_or_legal_approval() -> None:
    source = APP.read_text(encoding="utf-8")
    forbidden = ("已通过产线验收", "已获得企业授权", "法律电子签名", "真人专家已批准")
    assert not any(text in source for text in forbidden)
    assert "st.chat_input" not in source
    assert "赛道适配矩阵" not in source
    assert "API Key（仅本轮内存" not in source
    assert "应用负责进入真实业务流程" not in source
    assert "真实用户 · 真实任务形态" not in source
