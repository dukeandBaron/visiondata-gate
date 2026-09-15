from __future__ import annotations

from pathlib import Path
import re
import tomllib

from visiondata_gate.learning_contracts import FeedbackReview
from visiondata_gate.learning_yolo_backend import YoloTrainingConfig
from tools.export_public_repository import _selected


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    path = ROOT / relative
    assert path.is_file(), f"missing normative review artifact: {relative}"
    return path.read_text(encoding="utf-8")


def test_normative_terminology_defines_three_stages_and_five_control_functions() -> None:
    document = _read("docs/TECHNICAL_TERMINOLOGY.md")
    for identifier in (
        "HUMAN_AI_COLLABORATIVE_DATASET_BOOTSTRAP",
        "AGENT_ORCHESTRATED_DATA_QUALITY_GOVERNANCE",
        "GOVERNED_MODEL_DEVELOPMENT_AND_FEEDBACK",
        "DATA_QUALITY_DIAGNOSER",
        "REMEDIATION_PLANNER",
        "AUTHORIZED_REMEDIATION_EXECUTOR",
        "INDEPENDENT_VERIFICATION_GATE",
        "EVIDENCE_GAP_DRIVEN_BOUNDED_REPLANNER",
        "DIAGNOSIS_REVISION",
        "REMEDIATION_REVISION",
    ):
        assert identifier in document


def test_review_closure_keeps_unimplemented_model_routes_explicit() -> None:
    document = _read("docs/REVIEW_GUIDANCE_CLOSURE_20260915.md")
    for boundary in (
        "VLM_ASSISTED_PRE_ANNOTATION=PLANNED_NOT_CONNECTED",
        "SUPERVISED_BBOX_DETECTOR=BOUNDED_LOCAL_RUNTIME",
        "NORMALITY_PROXY=PUBLIC_DEVELOPMENT_ONLY",
        "MASK_GENERATION=NOT_IMPLEMENTED",
        "TOP_K_SAMPLE_MINING=NOT_IMPLEMENTED",
        "ACTIVE_LEARNING_QUERY_ENGINE=NOT_IMPLEMENTED",
        "TTT_RUNTIME=NOT_IMPLEMENTED",
        "production_release_allowed=false",
    ):
        assert boundary in document


def test_normative_review_documents_are_part_of_the_public_source_contract() -> None:
    assert _selected("docs/TECHNICAL_TERMINOLOGY.md")
    assert _selected("docs/REVIEW_GUIDANCE_CLOSURE_20260915.md")


def test_vlm_preannotation_is_not_conflated_with_other_learning_paradigms() -> None:
    document = _read("docs/TECHNICAL_TERMINOLOGY.md")
    for term in (
        "VLM-assisted pre-annotation",
        "Pseudo-labeling",
        "Knowledge distillation",
        "Weak supervision",
    ):
        assert term in document
    assert "CURRENT_VLM_LEARNING_PARADIGM=NONE" in document


def test_package_description_and_council_name_do_not_overstate_external_ai() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["description"] == (
        "Auditable industrial-vision dataset governance and model-development Agent"
    )
    terminology = _read("docs/TECHNICAL_TERMINOLOGY.md")
    assert "Deterministic Evidence Council" in terminology
    assert "AI Expert Council" in terminology
    assert "legacy display label" in terminology


def test_primary_narrative_uses_canonical_dataset_lifecycle_terms() -> None:
    documents = "\n".join(
        _read(path)
        for path in (
            "README.md",
            "docs/DEFENSE_3MIN_SCRIPT_SEMIFINAL.md",
            "docs/INDUSTRIAL_INSPECTION_ROUTE.md",
        )
    )
    for term in (
        "人机协同数据集冷启动",
        "Agent 编排的数据质量治理",
        "受控模型开发与反馈回流",
        "初始候选数据集版本",
        "经治理的数据集候选版本",
    ):
        assert term in documents
    for ambiguous in (
        "Accurate Dataset",
        "accurate dataset",
        "精准数据集",
        "粗糙数据集",
        "自动生成真值",
        "Agent 自动修复产线",
        "test and train",
    ):
        assert ambiguous not in documents
    assert _read("docs/INDUSTRIAL_INSPECTION_ROUTE.md").startswith(
        "# VisionData Gate"
    )


def test_user_facing_feedback_terms_preserve_human_adjudication_boundary() -> None:
    content = _read("web/src/components/VisionModelWorkbench.tsx") + _read(
        "web/src/pages/LearningLoopPage.tsx"
    )
    assert "困难样本候选（人工裁定）" in content
    assert "标签复核候选（尚未确认错误）" in content
    assert "有效难例" not in content
    assert "困难样本（人工判断）" not in content


def test_source_docstrings_separate_feedback_detection_and_normality_scopes() -> None:
    assert "human-adjudicated" in (FeedbackReview.__doc__ or "")
    assert "bounding-box" in (YoloTrainingConfig.__doc__ or "")
    experiment_source = _read("src/visiondata_gate/model_experiment_agent.py")
    assert "normality proxy" in experiment_source
    assert "not the supervised bounding-box detector" in experiment_source


def test_three_minute_defense_script_has_a_speakable_character_budget() -> None:
    document = _read("docs/DEFENSE_3MIN_SCRIPT_SEMIFINAL.md")
    rows = re.findall(
        r"\| (\d{2}):(\d{2})–(\d{2}):(\d{2}) \| \d+ \| “([^”]+)” \|",
        document,
    )
    assert len(rows) == 12
    total = 0
    for start_min, start_sec, end_min, end_sec, narration in rows:
        duration = (int(end_min) * 60 + int(end_sec)) - (
            int(start_min) * 60 + int(start_sec)
        )
        assert duration > 0
        assert len(narration) <= duration * 5
        total += len(narration)
    assert total <= 780


def test_governance_output_is_explicitly_conditional_and_fail_closed() -> None:
    terminology = _read("docs/TECHNICAL_TERMINOLOGY.md")
    assert (
        "**经治理的数据集候选版本**（仅在必要条件满足时；否则 `HOLD`）"
        in terminology
    )


def test_review_architecture_uses_a_stable_feedback_node() -> None:
    document = _read("docs/REVIEW_GUIDANCE_CLOSURE_20260915.md")
    assert 'FEEDBACK["新采集 / 标签复核 / 分布变化"]' in document
    assert "FEEDBACK -.-> BOOT" in document
    assert 'TRAIN -. "' not in document


def test_spoken_answers_state_the_boundary_without_repeating_rejected_label() -> None:
    review_answer = _read("docs/REVIEW_GUIDANCE_CLOSURE_20260915.md").split(
        "## 40 秒标准回答", maxsplit=1
    )[1]
    terminology_answer = _read("docs/TECHNICAL_TERMINOLOGY.md").split(
        "## 答辩中的标准短句", maxsplit=1
    )[1]
    for answer in (review_answer, terminology_answer):
        assert "不作数据准确性已经独立证明的结论" in answer
        assert "不是“精准数据集”" not in answer


def test_product_readme_surfaces_current_architecture_and_version_evolution() -> None:
    readme = _read("README.md")
    public_template = _read("docs/PUBLIC_REPOSITORY_README.md")
    assert readme == public_template
    for term in (
        "人机协同数据集冷启动",
        "Agent 编排的数据质量治理",
        "受控模型开发与反馈回流",
        "DIAGNOSIS_REVISION",
        "REMEDIATION_REVISION",
        "docs/TECHNICAL_TERMINOLOGY.md",
        "docs/REVIEW_GUIDANCE_CLOSURE_20260915.md",
        "docs/VERSION_EVOLUTION.md",
    ):
        assert term in readme


def test_version_evolution_separates_milestones_packages_builds_and_evidence() -> None:
    assert _selected("docs/VERSION_EVOLUTION.md")
    document = _read("docs/VERSION_EVOLUTION.md")
    for identifier in (
        "vdg-20260816-rc1",
        "v0.1.0-goai-rc2",
        "v0.3.0-goai-rc3",
        "v0.4.0-goai-semifinal-rc4",
        "windows-local-ce72604-20260914",
        "windows-local-dc3a4b-login-fix-20260915",
        "CURRENT_SOURCE_UNRELEASED",
        "production_release_allowed=false",
    ):
        assert identifier in document
    assert "竞赛里程碑 ≠ Python 包版本 ≠ Windows 构建身份 ≠ Git 提交" in document
    assert "旧版本回执不会自动证明当前源码或新安装包" in document


def test_product_docs_surface_latest_model_and_installer_boundaries() -> None:
    readme = _read("README.md")
    for token in (
        "10–600 秒",
        "同一分区的字节重复或解码像素重复",
        "BUILD_MANIFEST.json",
        "SOURCE_MANIFEST.json",
        "DELIVERY_STATUS.json",
        "SHA256SUMS.txt",
        "docs/VISION_MODEL_API_CONTRACT.md",
        "docs/MODEL_JOB_RETENTION.md",
    ):
        assert token in readme
    for document in (
        "docs/VISION_MODEL_API_CONTRACT.md",
        "docs/MODEL_JOB_RETENTION.md",
    ):
        assert _selected(document)
        assert _read(document)
    installer = _read("docs/WINDOWS_INSTALLER.md")
    for artifact in (
        "BUILD_MANIFEST.json",
        "SOURCE_MANIFEST.json",
        "DELIVERY_STATUS.json",
        "SHA256SUMS.txt",
        "BUILD_COMPLETE_VALIDATION_PENDING",
    ):
        assert artifact in installer
