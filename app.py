from __future__ import annotations

import base64
import csv
import hashlib
import html
import io
import json
import os
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import streamlit as st
from pydantic import ValidationError

from visiondata_gate.annotation_roundtrip import (
    AnnotationExportRecord,
    AnnotationImportPackage,
    AnnotationProvider,
)
from visiondata_gate.capa import (
    ApproveRemediationPlanRequest,
    SelectRemediationPlanRequest,
)
from visiondata_gate.contracts import GateResult
from visiondata_gate.demo_fixtures import build_fixture_industrial_incident_request
from visiondata_gate.evidence import canonical_json_bytes
from visiondata_gate.dynamic_benchmark import (
    DynamicBenchmarkValidationError,
    load_dynamic_benchmark_report,
)
from visiondata_gate.incident_canvas import build_incident_canvas
from visiondata_gate.industrial_incident import (
    IncidentHumanDecision,
    IndustrialIncidentDecisionRequest,
    parse_industrial_incident_request_json,
)
from visiondata_gate.lineage import CreateReverificationRequest
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
from visiondata_gate.product_service import (
    ArtifactUnavailableError,
    ProductService,
    ProductServiceError,
    get_product_service,
)
from visiondata_gate.release import (
    DEFAULT_RELEASE_ID,
    SCENARIO_DELIVERY_FILENAME,
    ReleaseValidationError,
    SubmissionRelease,
    load_submission_release,
)
from visiondata_gate.reviewer_canvas import build_reviewer_canvas
from visiondata_gate.runtime_canvas import build_runtime_canvas
from visiondata_gate.runtime_models import RuntimeTrace, ScenarioProfile
from visiondata_gate.task_store import ProductStoreError
from visiondata_gate.tools import tool_catalog


PROJECT_ROOT = Path(__file__).resolve().parent
PRODUCT_ROOT = Path(
    os.environ.get("VISIONDATA_UI_PRODUCT_ROOT", PROJECT_ROOT / "output" / "product")
)
SERVICE: ProductService = get_product_service(PRODUCT_ROOT)

TOOL_LABELS = {
    "image_quality": "图像质量",
    "duplicate_leakage": "重复与泄漏",
    "annotation_integrity": "标注完整性",
    "coverage_matrix": "覆盖完整性",
    "governance_audit": "治理审计",
}
FINDING_LABELS = {
    "ANNOTATION_DIMENSION_MISMATCH": "标注尺寸不匹配",
    "COVERAGE_GAP": "采集覆盖缺口",
    "CROSS_TOOL_ACTION_CONFLICT": "跨工具处置冲突",
    "CROSS_SPLIT_EXACT_DUPLICATE": "跨数据集精确重复",
    "CROSS_SPLIT_NEAR_DUPLICATE": "跨数据集近似重复",
    "DECODE_FAILURE": "图像无法解码",
    "EXACT_DUPLICATE": "批次内精确重复",
    "GOVERNANCE_SCOPE_GAP": "治理范围缺口",
    "INVALID_DIMENSIONS": "图像尺寸不合规",
    "LOW_SHARPNESS": "清晰度不足",
    "METADATA_COUNT_DRIFT": "元数据计数漂移",
    "MISSING_ANNOTATION": "缺少标注",
    "FOLLOWUP_BUDGET_EXHAUSTED": "补证预算不足",
    "FOLLOWUP_TOOL_ERROR": "补证工具失败",
    "NATIVE_RESOLUTION_EVIDENCE_INCOMPLETE": "分辨率证据不一致",
    "OVEREXPOSED": "过曝",
    "UNDEREXPOSED": "欠曝",
}
ACTION_LABELS = {
    "INVESTIGATE": "补充核查",
    "RECAPTURE": "重新采集",
    "RELABEL": "重新标注",
    "REMOVE_OR_REPARTITION": "移除或重新划分",
}
SCENARIO_LABELS = {
    "industrial": "工业视觉治理",
    "generic": "通用数据治理",
}
SOURCE_LABELS = {
    DataSourceKind.SYNTHETIC_DEMO.value: "合成演示数据",
    DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY.value: "本地授权工业数据",
    DataSourceKind.EXTERNAL_RESIDENCY_REFERENCE.value: "外部驻留数据引用",
}
DECISION_EXPLANATIONS = {
    "PASS": "当前数据版本满足冻结 Gate 合同；不等于异常根因关闭或生产放行。",
    "RECAPTURE": "当前证据触发整改门槛；完成工单后必须按同一规则重新复验。",
    "QUARANTINE": "当前数据版本需要隔离处理，不能作为异常恢复或生产放行证据。",
    "DEFER": "证据或必需能力不足，系统已安全暂缓且没有推测性放行。",
}
INCIDENT_STATUS_LABELS = {
    "EVIDENCE_INCOMPLETE": "证据待补齐",
    "INVESTIGATION_REQUIRED": "需要联合调查",
    "PLAN_AWAITING_APPROVAL": "方案待批准",
    "REVERIFICATION_REQUIRED": "需要独立复验",
    "READY_FOR_HUMAN_DECISION": "等待质量负责人决定",
    "CLOSED": "案件已关闭",
}
INCIDENT_RECOMMENDATION_LABELS = {
    "COLLECT_MORE_EVIDENCE": "补充关键证据",
    "CONTINUE_HOLD": "继续保持 HOLD",
    "SELECT_REMEDIATION_PLAN": "选择最小整改方案",
    "REVERIFY_VISION_SOLUTION": "复验视觉方案",
    "RECOVERY_CANDIDATE": "进入人工恢复评估",
    "RECAPTURE_REQUIRED": "需要重新采集",
    "ESCALATE_TO_ENGINEER": "转专业责任人调查",
}

EXTERNAL_GATE_RESULT_ENV = "VISIONDATA_UI_EXTERNAL_GATE_RESULT"
PUBLIC_RELEASE_DIR_ENV = "VISIONDATA_UI_RELEASE_DIR"
DYNAMIC_BENCHMARK_ENV = "VISIONDATA_UI_DYNAMIC_BENCHMARK"
DYNAMIC_BENCHMARK_SHA256_ENV = "VISIONDATA_UI_DYNAMIC_BENCHMARK_SHA256"
INITIAL_PAGE_ENV = "VISIONDATA_UI_INITIAL_PAGE"
DEFAULT_DYNAMIC_BENCHMARK_SHA256 = (
    "2623cb1c11738a35a052f8edb45488be85c1b2698d99bf907c2871305117ff8b"
)
DEFAULT_DYNAMIC_BENCHMARK_PATH = (
    PROJECT_ROOT
    / "output"
    / "goai_rc3_dynamic_bench_20260825"
    / "dynamic_benchmark.json"
)
SYNTHETIC_VISUAL_ROOT = PROJECT_ROOT / "07_results" / "frozen_demo_20260809"

st.set_page_config(
    page_title="VisionData Gate · 换型后视觉异常处置 Agent",
    page_icon="◇",
    layout="wide",
    initial_sidebar_state="auto",
)

st.markdown(
    """
<style>
:root {
  --surface:#ffffff; --surface-soft:#f7f8fa; --bg:#f4f5f7; --ink:#16181d;
  --muted:#656970; --subtle:#8b9098; --line:#e7e9ed; --line-strong:#d9dde4;
  --blue:#1769e0; --blue-hover:#0f5bc9; --blue-soft:#edf4ff;
  --green:#137a3a; --green-soft:#ebf8ef; --amber:#9a5b00; --amber-soft:#fff5dd;
  --red:#b3261e; --red-soft:#fceceb; --shadow:0 18px 55px rgba(25,36,54,.065);
}
html { color-scheme:light; }
.stApp { background:
  radial-gradient(circle at 78% -8%,rgba(44,112,240,.065),transparent 29rem),
  linear-gradient(180deg,#fafbfc 0,#f4f5f7 28rem); color:var(--ink); }
#MainMenu, footer, [data-testid="stAppDeployButton"] { display:none !important; }
header[data-testid="stHeader"] { background:rgba(250,251,252,.76); backdrop-filter:blur(22px) saturate(150%); border-bottom:1px solid rgba(226,229,235,.72); }
.block-container { max-width:1260px; padding-top:2rem; padding-bottom:5.5rem; }
h1,h2,h3,h4,p,li,button,label,input,textarea { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif; }
h1,h2,h3,h4 { color:var(--ink); letter-spacing:-.035em; text-wrap:balance; }
h1 { font-size:clamp(2rem,3vw,3rem); line-height:1.08; margin-bottom:.45rem; }
p,li,.stCaption { color:var(--muted); }
section[data-testid="stSidebar"] { background:rgba(255,255,255,.90); border-right:1px solid rgba(222,225,231,.9); backdrop-filter:blur(24px); }
section[data-testid="stSidebar"] > div { padding-top:1.15rem; }
section[data-testid="stSidebar"] [data-testid="stRadioGroup"] { gap:.2rem; }
section[data-testid="stSidebar"] [data-testid="stRadioOption"] { border-radius:11px; padding:.48rem .58rem; transition:background .16s ease,color .16s ease; }
section[data-testid="stSidebar"] [data-testid="stRadioOption"]:hover { background:#f4f6f9; }
section[data-testid="stSidebar"] [data-testid="stRadioOption"][data-selected="true"] { background:var(--blue-soft); }
section[data-testid="stSidebar"] [data-testid="stRadioOption"] [data-testid="stMarkdownContainer"] p { color:#515156; font-weight:560; }
section[data-testid="stSidebar"] [data-testid="stRadioOption"][data-selected="true"] [data-testid="stMarkdownContainer"] p { color:var(--blue); font-weight:700; }
section[data-testid="stSidebar"] [data-testid="stRadioOption"] [class*="etak9234"] { display:none; }
.vg-eyebrow { color:var(--blue); font-size:.67rem; font-weight:750; letter-spacing:.1em; text-transform:uppercase; }
.vg-brand { display:flex; gap:.7rem; align-items:center; padding:.15rem 0 1rem; }
.vg-logo { display:grid; place-items:center; width:38px; height:38px; border-radius:13px; color:#fff;
  background:linear-gradient(145deg,#0b57d0,#4c8df7); box-shadow:0 10px 28px rgba(23,105,224,.22); font-weight:800; }
.vg-brand b { display:block; color:var(--ink); font-size:.94rem; }
.vg-brand span { display:block; color:#8a8a90; font-size:.68rem; margin-top:.12rem; }
.vg-context { padding:.82rem .92rem; margin:.2rem 0 1rem; border:1px solid var(--line); border-radius:15px; background:rgba(247,248,250,.82); }
.vg-context small { color:#8a8a90; font-size:.66rem; }
.vg-context b { display:block; color:var(--ink); font-size:.82rem; margin:.12rem 0; }
.vg-context span { color:var(--muted); font-size:.7rem; }
.vg-hero { position:relative; display:grid; grid-template-columns:minmax(0,1.62fr) minmax(280px,.72fr); gap:2.4rem; align-items:end;
  padding:2.75rem 2.8rem; border:1px solid rgba(255,255,255,.58); border-radius:32px; color:#fff; overflow:hidden;
  background:radial-gradient(circle at 84% 0,rgba(151,197,255,.35),transparent 32%),linear-gradient(135deg,#102951 0,#1258bd 56%,#3f7ee8 100%);
  box-shadow:0 28px 80px rgba(26,70,139,.17); }
.vg-hero::after { content:""; position:absolute; right:-6rem; bottom:-9rem; width:25rem; height:25rem; border-radius:50%; border:1px solid rgba(255,255,255,.12); box-shadow:0 0 0 4rem rgba(255,255,255,.035),0 0 0 8rem rgba(255,255,255,.025); pointer-events:none; }
.vg-hero > * { position:relative; z-index:1; }
.vg-kicker { font-size:.68rem; letter-spacing:.14em; font-weight:750; color:#cfe1ff; }
.vg-hero h1 { color:#fff; font-size:clamp(2.25rem,3.5vw,3.75rem); line-height:1.02; margin:.6rem 0 .9rem; max-width:820px; }
.vg-hero p { color:#dce9ff; max-width:730px; line-height:1.78; font-size:.94rem; margin:0; }
.vg-hero-side { padding:1.15rem 1.2rem; border-radius:20px; background:rgba(255,255,255,.12); border:1px solid rgba(255,255,255,.2); backdrop-filter:blur(14px); }
.vg-hero-side small { color:#cfe1ff; }
.vg-hero-side b { display:block; margin:.25rem 0; color:#fff; font-size:1.1rem; }
.vg-hero-side span { color:#dce9ff; font-size:.74rem; }
.vg-head { display:flex; align-items:end; justify-content:space-between; gap:1rem; margin:2.45rem 0 .9rem; }
.vg-head h2 { margin:0; font-size:1.4rem; }
.vg-head span { color:#8a8a90; font-size:.74rem; }
.vg-card { height:100%; padding:1.2rem 1.25rem; border:1px solid var(--line); border-radius:20px; background:rgba(255,255,255,.88); box-shadow:0 10px 34px rgba(30,40,60,.035); }
.vg-card small { color:#8a8a90; font-size:.68rem; }
.vg-card h3 { margin:.28rem 0 .45rem; font-size:1rem; }
.vg-card p { margin:0; font-size:.77rem; line-height:1.6; }
.vg-entry-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:1rem; }
.vg-entry { position:relative; min-height:178px; padding:1.3rem; border:1px solid var(--line); border-radius:22px; background:rgba(255,255,255,.86); box-shadow:0 12px 38px rgba(31,41,55,.04); overflow:hidden; }
.vg-entry::after { content:""; position:absolute; inset:auto -36px -48px auto; width:116px; height:116px; border-radius:50%; background:var(--blue-soft); opacity:.72; }
.vg-entry small { color:var(--blue); font-size:.66rem; font-weight:750; letter-spacing:.08em; }
.vg-entry h3 { margin:.72rem 0 .45rem; font-size:1.05rem; }
.vg-entry p { max-width:92%; margin:0; color:var(--muted); font-size:.76rem; line-height:1.65; }
.vg-entry code { display:inline-block; margin-top:.85rem; padding:.28rem .48rem; border-radius:8px; background:#f4f6f9; color:#4b5563; font-size:.66rem; }
.vg-status { display:inline-flex; align-items:center; gap:.35rem; padding:.28rem .55rem; border-radius:999px; font-size:.67rem; font-weight:700; }
.vg-status.ok { color:var(--green); background:var(--green-soft); }
.vg-status.warn { color:var(--amber); background:var(--amber-soft); }
.vg-status.info { color:var(--blue); background:var(--blue-soft); }
.vg-status.fail { color:var(--red); background:var(--red-soft); }
.vg-dot { width:6px; height:6px; border-radius:50%; background:currentColor; }
.vg-metric { position:relative; padding:1.05rem 1.1rem; border-top:1px solid var(--line-strong); background:transparent; }
.vg-metric::before { content:""; position:absolute; left:0; top:-1px; width:2.2rem; height:2px; border-radius:99px; background:var(--blue); }
.vg-metric small { display:block; color:#8a8a90; font-size:.67rem; }
.vg-metric b { display:block; color:var(--ink); font-size:1.45rem; margin-top:.25rem; letter-spacing:-.04em; }
.vg-task { padding:1rem .2rem; border:0; border-bottom:1px solid var(--line); background:transparent; margin:0; }
.vg-task-top { display:flex; justify-content:space-between; gap:1rem; align-items:center; }
.vg-task b { color:var(--ink); font-size:.84rem; }
.vg-task p { margin:.35rem 0 0; font-size:.72rem; }
.vg-task code { color:#6e6e73; background:#f3f4f6; padding:.14rem .32rem; border-radius:5px; }
.vg-decision { position:relative; min-height:180px; padding:1.45rem 1.55rem; border-radius:24px; border:1px solid var(--line); background:linear-gradient(145deg,#fff,#f8f9fb); box-shadow:var(--shadow); overflow:hidden; }
.vg-decision::after { content:""; position:absolute; width:130px; height:130px; right:-42px; bottom:-52px; border-radius:50%; background:var(--amber-soft); opacity:.8; }
.vg-decision small { color:#8a8a90; }
.vg-decision b { display:block; margin:.3rem 0; font-size:1.75rem; }
.vg-decision.pass b { color:var(--green); } .vg-decision.recapture b,.vg-decision.quarantine b { color:var(--amber); } .vg-decision.defer b { color:var(--red); }
.vg-timeline { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:0; padding:1rem 1.15rem; border:1px solid var(--line); border-radius:20px; background:rgba(255,255,255,.78); box-shadow:0 12px 40px rgba(30,40,60,.035); }
.vg-step { position:relative; min-width:0; padding:.2rem .9rem .2rem 1.35rem; border:0; background:transparent; }
.vg-step::before { content:""; position:absolute; left:.1rem; top:.48rem; width:.62rem; height:.62rem; border:2px solid #c9ced6; border-radius:50%; background:#fff; z-index:2; }
.vg-step:not(:last-child)::after { content:""; position:absolute; left:.72rem; right:-.12rem; top:.76rem; height:1px; background:#dfe3e8; }
.vg-step.current { color:var(--blue); }
.vg-step.done { color:var(--green); }
.vg-step.current::before { border-color:var(--blue); background:var(--blue); box-shadow:0 0 0 4px var(--blue-soft); }
.vg-step.done::before { border-color:var(--green); background:var(--green); }
.vg-step small { display:block; color:inherit; opacity:.78; font-size:.6rem; }
.vg-step b { display:block; color:inherit; font-size:.72rem; margin-top:.15rem; }
.vg-code { border:1px solid #263248; border-radius:16px; background:#111827; padding:1rem 1.1rem; color:#dbeafe; font:12px/1.7 "Cascadia Code",Consolas,monospace; overflow:auto; }
.vg-boundary { padding:1rem 1.1rem; border-radius:17px; background:#fff9ed; border:1px solid #f0d9a5; color:#785000; font-size:.76rem; line-height:1.65; }
div[data-testid="stCode"] { max-width:100%; }
div[data-testid="stCode"] code { white-space:pre; }
div[data-testid="stMetric"] { padding:.95rem 1rem; border:0; border-top:1px solid var(--line-strong); border-radius:0; background:transparent; }
div[data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:16px; overflow:hidden; background:#fff; }
.stButton > button { border-radius:13px; min-height:2.8rem; font-weight:650; border-color:var(--line-strong); transition:transform .15s ease,box-shadow .15s ease,background .15s ease; }
.stButton > button:hover { transform:translateY(-1px); }
.stButton > button[kind="primary"] { border:0; color:#fff; background:var(--blue); box-shadow:0 10px 24px rgba(23,105,224,.19); }
.stButton > button[kind="primary"]:hover { background:var(--blue-hover); }
.stButton > button[kind="primary"] p { color:#fff !important; }
.stTabs [data-baseweb="tab-list"] { gap:.3rem; border-bottom:1px solid var(--line); }
.stTabs [data-baseweb="tab"] { height:2.8rem; color:#76767b; }
.vg-evidence-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:.75rem; }
.vg-evidence-item { min-width:0; padding:1.15rem 1.2rem; border:1px solid var(--line); border-radius:19px; background:rgba(255,255,255,.88); box-shadow:0 10px 30px rgba(30,40,60,.03); }
.vg-evidence-top { display:flex; align-items:flex-start; justify-content:space-between; gap:.65rem; }
.vg-evidence-top small { color:var(--blue); font-weight:700; }
.vg-evidence-item h3 { margin:.32rem 0 .5rem; font-size:.94rem; }
.vg-evidence-item p { margin:.22rem 0; font-size:.73rem; line-height:1.55; overflow-wrap:anywhere; }
.vg-evidence-item b { color:#49494d; }
.vg-metrics-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:1.1rem; }
.vg-live { margin-top:1.1rem; padding:1.25rem 1.35rem; border:1px solid #dfe6f0; border-radius:23px; background:linear-gradient(145deg,rgba(255,255,255,.95),rgba(244,248,255,.95)); box-shadow:var(--shadow); }
.vg-live-top { display:flex; align-items:flex-start; justify-content:space-between; gap:1rem; }
.vg-live h3 { margin:.4rem 0 .45rem; font-size:1.15rem; }
.vg-live p { margin:0; max-width:850px; font-size:.78rem; line-height:1.65; }
.vg-live-grid { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:.65rem; margin-top:1.05rem; }
.vg-live-stat { padding:.75rem .82rem; border-left:2px solid #b8cff4; background:rgba(255,255,255,.55); }
.vg-live-stat small { display:block; color:var(--subtle); font-size:.63rem; }
.vg-live-stat b { display:block; margin-top:.2rem; color:var(--ink); font-size:1.05rem; overflow-wrap:anywhere; }
.vg-live-hash { margin-top:.85rem; color:var(--subtle); font:10px/1.5 "Cascadia Code",Consolas,monospace; overflow-wrap:anywhere; }
.vg-cluster { display:flex; flex-wrap:wrap; gap:.45rem; margin-top:.9rem; }
.vg-cluster span { padding:.34rem .52rem; border:1px solid var(--line); border-radius:999px; background:#fff; color:#5f6670; font-size:.66rem; }
.vg-section-intro { max-width:780px; margin:.2rem 0 1.6rem; color:var(--muted); font-size:.88rem; line-height:1.7; }
.vg-detail-hero { display:grid; grid-template-columns:minmax(0,.78fr) minmax(0,1.22fr); gap:1.2rem; align-items:stretch; margin:1.15rem 0 1.6rem; }
.vg-detail-metrics { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:.8rem; padding:1.3rem; border:1px solid var(--line); border-radius:24px; background:rgba(255,255,255,.82); box-shadow:0 16px 50px rgba(30,40,60,.04); }
.vg-detail-metric { padding:.35rem .55rem; }
.vg-detail-metric small { display:block; color:var(--subtle); font-size:.67rem; }
.vg-detail-metric b { display:block; margin-top:.25rem; color:var(--ink); font-size:1.75rem; }
.vg-detail-config { grid-column:1/-1; padding-top:.8rem; border-top:1px solid var(--line); color:var(--muted); font-size:.72rem; line-height:1.6; }
.vg-empty-evidence { padding:1rem 1.1rem; border:1px dashed var(--line-strong); border-radius:18px; color:var(--muted); background:rgba(255,255,255,.5); }
.vg-review-hero { position:relative; padding:2.7rem 2.8rem; border:1px solid rgba(255,255,255,.62); border-radius:32px; overflow:hidden; color:#fff; background:radial-gradient(circle at 86% 4%,rgba(141,194,255,.36),transparent 31%),linear-gradient(132deg,#0d2347 0,#145dca 58%,#4c83ec 100%); box-shadow:0 30px 85px rgba(26,70,139,.18); }
.vg-review-hero::after { content:""; position:absolute; right:-7rem; bottom:-10rem; width:27rem; height:27rem; border:1px solid rgba(255,255,255,.13); border-radius:50%; box-shadow:0 0 0 4.5rem rgba(255,255,255,.035),0 0 0 9rem rgba(255,255,255,.022); pointer-events:none; }
.vg-review-hero > * { position:relative; z-index:1; }
.vg-review-badges { display:flex; flex-wrap:wrap; gap:.48rem; margin-bottom:1.05rem; }
.vg-review-badges span { padding:.38rem .62rem; border:1px solid rgba(255,255,255,.24); border-radius:999px; background:rgba(255,255,255,.11); color:#e5efff; font-size:.66rem; font-weight:700; backdrop-filter:blur(9px); }
.vg-review-hero h1 { max-width:830px; margin:0 0 .85rem; color:#fff; font-size:clamp(2.3rem,3.7vw,3.9rem); line-height:1.02; }
.vg-review-hero p { max-width:810px; margin:0; color:#dce9ff; font-size:.94rem; line-height:1.8; }
.vg-review-proof { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:.65rem; margin-top:1.6rem; max-width:920px; }
.vg-review-proof div { padding:.78rem .86rem; border-left:2px solid rgba(207,225,255,.55); background:rgba(255,255,255,.07); }
.vg-review-proof small { display:block; color:#c8dcff; font-size:.62rem; }
.vg-review-proof b { display:block; margin-top:.2rem; color:#fff; font-size:1.13rem; }
.vg-story-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:1rem; }
.vg-story-card { min-height:190px; padding:1.3rem 1.35rem; border:1px solid var(--line); border-radius:22px; background:rgba(255,255,255,.88); box-shadow:0 12px 38px rgba(31,41,55,.04); }
.vg-story-card small { color:var(--blue); font-size:.66rem; font-weight:780; letter-spacing:.08em; }
.vg-story-card h3 { margin:.62rem 0 .48rem; font-size:1.06rem; }
.vg-story-card p { margin:0; font-size:.77rem; line-height:1.7; }
.vg-proof-ladder { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:1rem; position:relative; }
.vg-proof-level { position:relative; min-height:238px; padding:1.35rem 1.35rem 1.2rem; border:1px solid var(--line); border-radius:24px; background:rgba(255,255,255,.91); box-shadow:0 14px 42px rgba(31,41,55,.045); overflow:hidden; }
.vg-proof-level::after { content:""; position:absolute; inset:0 0 auto; height:3px; background:linear-gradient(90deg,#1769e0,#5b9af5); }
.vg-proof-level.public::after { background:linear-gradient(90deg,#0f8a4c,#59b978); }
.vg-proof-level.next::after { background:linear-gradient(90deg,#c27605,#e8af4c); }
.vg-proof-top { display:flex; align-items:center; justify-content:space-between; gap:.65rem; }
.vg-proof-index { color:var(--subtle); font-size:.63rem; font-weight:780; letter-spacing:.09em; }
.vg-proof-chip { display:inline-flex; align-items:center; gap:.35rem; padding:.3rem .52rem; border-radius:999px; color:var(--blue); background:var(--blue-soft); font-size:.62rem; font-weight:780; }
.vg-proof-level.public .vg-proof-chip { color:var(--green); background:var(--green-soft); }
.vg-proof-level.next .vg-proof-chip { color:var(--amber); background:var(--amber-soft); }
.vg-proof-level h3 { margin:.9rem 0 .36rem; font-size:1.16rem; }
.vg-proof-level > p { margin:0 0 .8rem; color:var(--muted); font-size:.75rem; line-height:1.6; }
.vg-proof-level ul { margin:.35rem 0 0; padding-left:1rem; }
.vg-proof-level li { margin:.36rem 0; color:#535862; font-size:.71rem; line-height:1.5; }
.vg-proof-callout { margin:.85rem 0 .15rem; padding:.8rem 1rem; border:1px solid #dfe7f3; border-radius:16px; color:#43546c; background:linear-gradient(135deg,#fbfdff,#f4f8ff); font-size:.73rem; line-height:1.65; }
.vg-loop { display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:.5rem; }
.vg-loop-step { position:relative; min-height:118px; padding:1rem .92rem; border:1px solid var(--line); border-radius:18px; background:rgba(255,255,255,.87); }
.vg-loop-step:not(:last-child)::after { content:"›"; position:absolute; right:-.48rem; top:2.55rem; z-index:2; color:#9eb5db; font-size:1.25rem; font-weight:700; }
.vg-loop-step small { color:var(--blue); font-size:.62rem; font-weight:800; }
.vg-loop-step b { display:block; margin:.48rem 0 .35rem; color:var(--ink); font-size:.82rem; }
.vg-loop-step span { color:var(--muted); font-size:.68rem; line-height:1.5; }
.vg-negative { padding:1.15rem 1.25rem; border:1px solid #d8e3f4; border-left:4px solid var(--blue); border-radius:18px; background:linear-gradient(135deg,#f8fbff,#f2f7ff); color:#4a5b73; font-size:.78rem; line-height:1.7; }
.vg-negative b { color:#163f7a; }
.vg-casebar { display:flex; flex-wrap:wrap; align-items:center; gap:.5rem 1rem; margin:1.15rem 0 .75rem; padding:.8rem 1rem; border:1px solid #dce2eb; border-radius:16px; background:#172235; color:#f8fafc; box-shadow:0 16px 40px rgba(18,30,49,.12); }
.vg-casebar b { color:#fff; font-size:.79rem; }
.vg-casebar span { color:#bac6d8; font-size:.68rem; }
.vg-casebar .hold { padding:.28rem .52rem; border:1px solid rgba(251,191,36,.36); border-radius:999px; color:#fcd57b; background:rgba(146,89,0,.28); font-weight:800; }
.vg-casebar .safe { margin-left:auto; color:#b9dfc8; }
.vg-case-grid { display:grid; grid-template-columns:minmax(205px,.72fr) minmax(340px,1.45fr) minmax(205px,.78fr); gap:.75rem; align-items:stretch; }
.vg-case-panel { min-width:0; padding:1rem 1.05rem; border:1px solid var(--line); border-radius:19px; background:rgba(255,255,255,.94); box-shadow:0 10px 30px rgba(30,40,60,.035); }
.vg-case-panel > small { display:block; margin-bottom:.75rem; color:var(--subtle); font-size:.61rem; font-weight:800; letter-spacing:.09em; }
.vg-version { position:relative; padding:.68rem .72rem .68rem 1rem; border-left:2px solid #b9cce9; }
.vg-version + .vg-version { margin-top:.34rem; }
.vg-version::before { content:""; position:absolute; left:-.35rem; top:.92rem; width:.58rem; height:.58rem; border:2px solid #7d9bc7; border-radius:50%; background:#fff; }
.vg-version.current { border-left-color:var(--amber); background:#fff9ed; border-radius:0 12px 12px 0; }
.vg-version.current::before { border-color:var(--amber); background:var(--amber); }
.vg-version b { display:block; color:var(--ink); font-size:.76rem; }
.vg-version span { display:block; margin-top:.18rem; color:var(--muted); font-size:.64rem; line-height:1.45; }
.vg-investigation { display:grid; grid-template-columns:1fr 1fr; gap:.55rem; }
.vg-fact { padding:.72rem .78rem; border:1px solid #e3e8f0; border-radius:13px; background:#f8fafc; }
.vg-fact small { display:block; color:var(--blue); font-size:.59rem; font-weight:800; letter-spacing:.06em; }
.vg-fact b { display:block; margin:.28rem 0 .18rem; color:var(--ink); font-size:.76rem; }
.vg-fact span { display:block; color:var(--muted); font-size:.64rem; line-height:1.45; }
.vg-hypotheses { grid-column:1/-1; margin-top:.15rem; border-top:1px solid var(--line); padding-top:.58rem; }
.vg-hypothesis { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:.6rem; align-items:center; padding:.42rem 0; }
.vg-hypothesis + .vg-hypothesis { border-top:1px dashed #e5e7eb; }
.vg-hypothesis b { color:#4b5563; font-size:.67rem; }
.vg-hypothesis span { padding:.23rem .42rem; border-radius:999px; font-size:.58rem; font-weight:800; }
.vg-hypothesis .supported { color:var(--green); background:var(--green-soft); }
.vg-hypothesis .open { color:var(--amber); background:var(--amber-soft); }
.vg-hypothesis .conflict { color:var(--red); background:var(--red-soft); }
.vg-profile-row { display:flex; align-items:center; justify-content:space-between; gap:.6rem; padding:.52rem 0; border-bottom:1px solid #edf0f4; }
.vg-profile-row:last-child { border-bottom:0; }
.vg-profile-row span { color:var(--muted); font-size:.63rem; }
.vg-profile-row b { color:#374151; font-size:.64rem; text-align:right; }
.vg-humanbar { position:sticky; bottom:.65rem; z-index:20; display:flex; flex-wrap:wrap; align-items:center; gap:.5rem; margin:.75rem 0 1.5rem; padding:.72rem .8rem; border:1px solid #d6dde8; border-radius:16px; background:rgba(255,255,255,.96); box-shadow:0 18px 45px rgba(31,41,55,.13); backdrop-filter:blur(16px); }
.vg-humanbar strong { margin-right:auto; color:#334155; font-size:.7rem; }
.vg-humanbar span { padding:.42rem .62rem; border:1px solid var(--line); border-radius:10px; color:#6b7280; background:#f8fafc; font-size:.63rem; font-weight:700; }
.vg-humanbar .primary { border-color:#e2b45c; color:#80520b; background:#fff6df; }
.vg-provenance { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:.55rem; }
.vg-provenance-node { position:relative; min-height:122px; padding:.88rem .82rem; border:1px solid var(--line); border-radius:16px; background:rgba(255,255,255,.9); }
.vg-provenance-node:not(:last-child)::after { content:"→"; position:absolute; right:-.47rem; top:2.85rem; z-index:2; color:#8fa9ce; font-weight:900; }
.vg-provenance-node small { color:var(--blue); font-size:.58rem; font-weight:800; }
.vg-provenance-node b { display:block; margin:.42rem 0 .28rem; color:var(--ink); font-size:.72rem; }
.vg-provenance-node span { display:block; color:var(--muted); font-size:.61rem; line-height:1.5; }
.vg-algorithm-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:.65rem; }
.vg-algorithm { padding:.9rem .92rem; border:1px solid var(--line); border-radius:16px; background:#fff; }
.vg-algorithm small { color:var(--blue); font-size:.59rem; font-weight:800; }
.vg-algorithm b { display:block; margin:.4rem 0 .28rem; color:var(--ink); font-size:.72rem; }
.vg-algorithm span { color:var(--muted); font-size:.62rem; line-height:1.5; }
@media (max-width:900px) {
  .block-container { padding:4.8rem .8rem 4rem; max-width:100%; }
  .vg-hero { grid-template-columns:1fr; padding:1.55rem 1.35rem; border-radius:22px; }
  .vg-timeline { grid-template-columns:1fr; gap:.1rem; padding:.8rem 1rem; }
  .vg-step { padding:.45rem .6rem .45rem 1.7rem; }
  .vg-step::before { left:.35rem; top:.72rem; }
  .vg-step:not(:last-child)::after { left:.67rem; right:auto; top:1.3rem; bottom:-.42rem; width:1px; height:auto; }
  .vg-head { align-items:start; flex-direction:column; }
  .vg-hero h1 { font-size:2rem; }
  .vg-task-top { align-items:flex-start; flex-direction:column; }
  .vg-evidence-grid { grid-template-columns:1fr; }
  .vg-entry-grid { grid-template-columns:1fr; }
  .vg-live-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .vg-detail-hero { grid-template-columns:1fr; }
  .vg-review-hero { padding:1.65rem 1.4rem; border-radius:23px; }
  .vg-review-proof { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .vg-story-grid { grid-template-columns:1fr; }
  .vg-proof-ladder { grid-template-columns:1fr; }
  .vg-proof-level { min-height:0; }
  .vg-loop { grid-template-columns:1fr 1fr; }
  .vg-loop-step:not(:last-child)::after { display:none; }
  div[data-testid="stHorizontalBlock"] { flex-wrap:wrap; }
  div[data-testid="column"] { min-width:min(100%,18rem) !important; flex:1 1 100% !important; width:100% !important; }
  section[data-testid="stSidebar"] { width:min(86vw,19rem) !important; background:#fff !important; box-shadow:18px 0 48px rgba(17,24,39,.18); }
  section[data-testid="stSidebar"][aria-expanded="false"] { min-width:0 !important; width:0 !important; }
  [data-testid="stSidebarContent"] { overflow-x:hidden; }
  div[data-testid="stDataFrame"] { max-width:calc(100vw - 1.6rem); overflow-x:auto; }
  .vg-metrics-grid { grid-template-columns:repeat(2,minmax(0,1fr)); gap:.65rem; }
  .vg-case-grid { grid-template-columns:1fr 1fr; }
  .vg-case-panel.middle { grid-column:1/-1; grid-row:1; }
  .vg-provenance { grid-template-columns:1fr; }
  .vg-provenance-node:not(:last-child)::after { content:"↓"; right:auto; left:50%; top:auto; bottom:-.58rem; }
  .vg-algorithm-grid { grid-template-columns:1fr 1fr; }
}
@media (max-width:480px) {
  header[data-testid="stHeader"] { background:rgba(245,245,247,.96); }
  .block-container { padding:4.35rem .7rem 3rem; }
  .vg-hero { padding:1.35rem 1.1rem; border-radius:20px; gap:1rem; }
  .vg-hero h1 { font-size:1.78rem; }
  .vg-hero p { font-size:.82rem; line-height:1.65; }
  .vg-head { margin:1.45rem 0 .7rem; gap:.2rem; }
  .vg-step { padding:.48rem .55rem .48rem 1.75rem; }
  .vg-card,.vg-metric,.vg-decision,.vg-evidence-item { border-radius:15px; }
  .vg-entry { min-height:0; border-radius:17px; }
  .vg-live { padding:1.05rem; border-radius:19px; }
  .vg-live-top { flex-direction:column; }
  .vg-live-grid { grid-template-columns:1fr 1fr; gap:.45rem; }
  .vg-live-stat { padding:.62rem .68rem; }
  .vg-detail-metrics { grid-template-columns:1fr; padding:1rem; }
  .vg-detail-config { grid-column:auto; }
  .vg-review-proof { grid-template-columns:1fr 1fr; }
  .vg-loop { grid-template-columns:1fr; }
  .vg-case-grid { grid-template-columns:1fr; }
  .vg-case-panel.middle { grid-column:auto; grid-row:auto; }
  .vg-investigation { grid-template-columns:1fr; }
  .vg-hypotheses { grid-column:auto; }
  .vg-casebar .safe { margin-left:0; width:100%; }
  .vg-humanbar { position:relative; bottom:auto; }
  .vg-humanbar strong { width:100%; }
  .vg-algorithm-grid { grid-template-columns:1fr; }
  .stTabs [data-baseweb="tab-list"] { overflow-x:auto; flex-wrap:nowrap; }
  .stTabs [data-baseweb="tab"] { flex:0 0 auto; padding-inline:.72rem; }
}
</style>
""",
    unsafe_allow_html=True,
)


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _status_badge(status: str) -> str:
    tone = {
        "COMPLETED": "ok",
        "PASS": "ok",
        "RUNNING": "info",
        "VERIFYING": "info",
        "PLANNED": "info",
        "CREATED": "info",
        "RECAPTURE": "warn",
        "QUARANTINE": "warn",
        "DEFER": "fail",
        "FAILED": "fail",
        "ARCHIVED": "warn",
    }.get(status, "info")
    labels = {
        "COMPLETED": "运行完成",
        "RUNNING": "正在审核",
        "VERIFYING": "正在复验",
        "PLANNED": "等待执行",
        "CREATED": "已创建",
        "PASS": "符合规则",
        "RECAPTURE": "需要整改",
        "QUARANTINE": "隔离处理",
        "DEFER": "暂缓处理",
        "FAILED": "运行失败",
        "ARCHIVED": "已归档",
    }
    label = labels.get(status, status)
    return f'<span class="vg-status {tone}"><i class="vg-dot"></i>{_e(label)}</span>'


def _metric(label: str, value: object) -> str:
    return f'<div class="vg-metric"><small>{_e(label)}</small><b>{_e(value)}</b></div>'


def _load_external_gate_result() -> tuple[GateResult | None, str | None]:
    """Load one explicitly mounted GateResult without exposing its source path."""

    configured_path = os.environ.get(EXTERNAL_GATE_RESULT_ENV, "").strip()
    if not configured_path:
        return None, None
    try:
        raw = Path(configured_path).read_bytes()
        result = GateResult.model_validate_json(raw)
    except (OSError, ValidationError, ValueError):
        return None, "已配置的受控 GateResult 无法读取或未通过结构校验。"
    return result, hashlib.sha256(raw).hexdigest()


def _load_public_release() -> tuple[SubmissionRelease | None, str | None]:
    """Load the cross-hashed public reviewer release without disclosing its path."""

    configured = os.environ.get(PUBLIC_RELEASE_DIR_ENV, "").strip()
    release_dir = (
        Path(configured)
        if configured
        else PROJECT_ROOT / "evidence" / "submission" / DEFAULT_RELEASE_ID
    )
    try:
        return load_submission_release(release_dir), None
    except (OSError, ReleaseValidationError, ValueError):
        return None, "公开评审证据缺失或一致性校验失败；评审模式已安全关闭。"


def _load_dynamic_benchmark() -> tuple[dict[str, Any] | None, str | None]:
    """Load the private RC3 orchestration benchmark without disclosing its path."""

    configured = os.environ.get(DYNAMIC_BENCHMARK_ENV, "").strip()
    report_path = Path(configured) if configured else DEFAULT_DYNAMIC_BENCHMARK_PATH
    if not report_path.is_file():
        return None, None
    try:
        raw = report_path.read_bytes()
        observed_sha256 = hashlib.sha256(raw).hexdigest()
        expected_sha256 = os.environ.get(
            DYNAMIC_BENCHMARK_SHA256_ENV,
            "" if configured else DEFAULT_DYNAMIC_BENCHMARK_SHA256,
        ).strip()
        if expected_sha256 and observed_sha256 != expected_sha256:
            raise DynamicBenchmarkValidationError(
                "DynamicBench report does not match the mounted SHA-256"
            )
        return load_dynamic_benchmark_report(report_path), None
    except (OSError, DynamicBenchmarkValidationError, ValueError):
        return None, "RC3 DynamicBench-v1 未通过结构、哈希或固定分母校验，已停止展示。"


def _external_gate_summary(result: GateResult) -> dict[str, Any]:
    finding_counts = Counter(item.code for item in result.findings)
    checks_passed = sum(item.status.value == "PASS" for item in result.rule_checks)
    sample_count = int(result.metrics.get("sample_count", 0))
    expert_count = len(result.council_trace.independent_opinions)
    tool_count = len(result.tool_trace)
    top_findings = sorted(finding_counts.items(), key=lambda item: (-item[1], item[0]))[
        :5
    ]
    return {
        "sample_count": sample_count,
        "finding_count": len(result.findings),
        "work_order_count": len(result.work_orders),
        "tool_count": tool_count,
        "expert_count": expert_count,
        "checks_passed": checks_passed,
        "checks_total": len(result.rule_checks),
        "top_findings": top_findings,
    }


def _render_external_gate_panel(result: GateResult | None, receipt: str | None) -> None:
    if result is None:
        if receipt:
            st.warning(receipt)
        else:
            st.markdown(
                '<div class="vg-empty-evidence"><b>受控真实证据未挂载</b><br><span>当前工作区仅展示本地演示运行；挂载通过结构校验的 GateResult 后，这里会显示固定分母、门禁结论与规则回执。</span></div>',
                unsafe_allow_html=True,
            )
        return
    summary = _external_gate_summary(result)
    decision_badge = _status_badge(result.decision.value)
    finding_chips = "".join(
        f"<span>{_e(_finding_label(code))} · {_e(count)}</span>"
        for code, count in summary["top_findings"]
    )
    st.markdown(
        f"""
<section class="vg-live">
  <div class="vg-live-top">
    <div><div class="vg-eyebrow">CONTROLLED REAL-DATA RECEIPT</div><h3>真实 Omni 固定样本 Gate</h3><p>该面板只读取已脱敏 GateResult；展示固定样本上的门禁结果、工具回执与规则稳定性，不读取或暴露原始图像、类别名、文件名和私有数据路径。</p><div class="vg-cluster"><span>批次 · {_e(result.batch_id)}</span><span>规则包 · {_e(result.policy_version)}</span></div></div>
    {decision_badge}
  </div>
  <div class="vg-live-grid">
    <div class="vg-live-stat"><small>固定分母</small><b>{summary["sample_count"]}</b></div>
    <div class="vg-live-stat"><small>Findings</small><b>{summary["finding_count"]}</b></div>
    <div class="vg-live-stat"><small>整改工单</small><b>{summary["work_order_count"]}</b></div>
    <div class="vg-live-stat"><small>工具回执</small><b>{summary["tool_count"]} 次</b></div>
    <div class="vg-live-stat"><small>规则检查</small><b>{summary["checks_passed"]}/{summary["checks_total"]}</b></div>
  </div>
  <div class="vg-cluster">{finding_chips}<span>AI 专家角色 · {_e(summary["expert_count"])}</span></div>
  <div class="vg-live-hash">GateResult SHA-256 · {_e(receipt or "unavailable")}</div>
</section>
""",
        unsafe_allow_html=True,
    )
    st.caption(
        "真实数据固定样本 Gate，不等同于全量数据认证、模型精度、客户现场、生产部署或生产批准。"
    )


def _scenario_label(value: object) -> str:
    raw = getattr(value, "value", value)
    return SCENARIO_LABELS.get(str(raw), str(raw))


def _source_label(value: object) -> str:
    raw = getattr(value, "value", value)
    return SOURCE_LABELS.get(str(raw), str(raw))


def _tool_label(value: object) -> str:
    return TOOL_LABELS.get(str(value), str(value))


def _finding_label(value: object) -> str:
    return FINDING_LABELS.get(str(value), str(value))


def _action_label(value: object) -> str:
    return ACTION_LABELS.get(str(value), str(value))


def _rerun() -> None:
    st.rerun()


def _bootstrap() -> tuple[Any, Any, Any]:
    return SERVICE.ensure_default_tenant()


def _active_context() -> tuple[Any, Any, list[Any], Any | None]:
    users = SERVICE.list_users()
    if not users:
        user, workspace, project = _bootstrap()
        return user, workspace, [project], project
    user_ids = [user.user_id for user in users]
    current_user_id = st.session_state.get("active_user_id")
    if current_user_id not in user_ids:
        current_user_id = user_ids[0]
    selected_user_id = st.selectbox(
        "当前用户",
        user_ids,
        index=user_ids.index(current_user_id),
        format_func=lambda value: next(
            user.display_name for user in users if user.user_id == value
        ),
        key="active_user_id",
    )
    user = next(item for item in users if item.user_id == selected_user_id)
    workspaces = SERVICE.list_workspaces(user.user_id)
    if not workspaces:
        return user, None, [], None
    workspace_ids = [item.workspace_id for item in workspaces]
    current_workspace = st.session_state.get("active_workspace_id")
    if current_workspace not in workspace_ids:
        current_workspace = workspace_ids[0]
    selected_workspace_id = st.selectbox(
        "当前工作区",
        workspace_ids,
        index=workspace_ids.index(current_workspace),
        format_func=lambda value: next(
            item.name for item in workspaces if item.workspace_id == value
        ),
        key="active_workspace_id",
    )
    workspace = next(
        item for item in workspaces if item.workspace_id == selected_workspace_id
    )
    projects = SERVICE.list_projects(user.user_id, workspace.workspace_id)
    project_ids = [item.project_id for item in projects]
    current_project = st.session_state.get("active_project_id")
    if current_project not in project_ids:
        current_project = project_ids[0] if project_ids else None
    project = next(
        (item for item in projects if item.project_id == current_project), None
    )
    return user, workspace, projects, project


def _render_sidebar() -> tuple[str, Any, Any, list[Any], Any | None]:
    with st.sidebar:
        st.markdown(
            '<div class="vg-brand"><div class="vg-logo">V</div><div><b>VisionData Gate</b><span>换型后视觉异常处置 Agent</span></div></div>',
            unsafe_allow_html=True,
        )
        user, workspace, projects, project = _active_context()
        if workspace is None:
            st.info("为当前用户创建一个工作区后即可开始。")
        else:
            st.markdown(
                f'<div class="vg-context"><small>当前空间</small><b>{_e(workspace.name)}</b><span>{len(projects)} 个项目 · 本地持久化</span></div>',
                unsafe_allow_html=True,
            )
        pages = [
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
        legacy_pages = {
            "概览": "工作台",
            "运行记录": "审核记录",
            "Skills": "能力目录",
            "信任与范围": "安全与权限",
            "系统边界": "安全与权限",
        }
        initial_page_aliases = {
            "workspace": "工作台",
            "incident": "异常处置",
            "reviewer": "评审模式",
            "projects": "项目",
            "sources": "数据源",
            "runs": "审核记录",
            "capabilities": "能力目录",
            "api": "API 接入",
            "security": "安全与权限",
        }
        configured_initial_page = os.environ.get(INITIAL_PAGE_ENV, "").strip()
        initial_page = initial_page_aliases.get(
            configured_initial_page.lower(), configured_initial_page
        )
        if "nav_section" not in st.session_state and initial_page in pages:
            st.session_state["nav_section"] = initial_page
        current_page = st.session_state.get("nav_section")
        if current_page in legacy_pages:
            st.session_state["nav_section"] = legacy_pages[current_page]
        pending_page = st.session_state.pop("_pending_nav", None)
        if pending_page in pages:
            st.session_state["nav_section"] = pending_page
        page = st.radio(
            "导航",
            pages,
            key="nav_section",
            label_visibility="collapsed",
        )
        st.divider()
        st.caption("本地模式 · 逻辑隔离（非登录认证）")
        if st.button("刷新任务状态", key="refresh_tasks", width="stretch"):
            _rerun()
    return page, user, workspace, projects, project


def _task_card(task: Any) -> None:
    decision = task.final_decision or task.initial_decision
    status_html = _status_badge(decision or task.execution_status.value)
    st.markdown(
        f"""
<div class="vg-task">
  <div class="vg-task-top"><b>{_e(task.goal[:92])}</b>{status_html}</div>
  <p><code>{_e(task.task_id)}</code> · {_e(_source_label(task.source_kind))} · 固定种子 {task.seed} · {task.updated_at[:19].replace("T", " ")}</p>
</div>
""",
        unsafe_allow_html=True,
    )
    if st.button("查看任务", key=f"open_{task.task_id}", width="stretch"):
        st.session_state["selected_task_id"] = task.task_id
        st.session_state["_pending_nav"] = "审核记录"
        _rerun()


def _render_task_form(user: Any, projects: list[Any], project: Any | None) -> None:
    st.markdown(
        '<div class="vg-head"><h2>创建异常调查任务</h2><span>提交后进入持久化运行队列</span></div>',
        unsafe_allow_html=True,
    )
    if not projects:
        st.info("请先在“项目”页面创建项目。")
        return
    project_ids = [item.project_id for item in projects]
    default_project = project.project_id if project else project_ids[0]
    catalog = tool_catalog()
    tools = [str(item["name"]) for item in catalog]
    with st.form("create_task_form", clear_on_submit=False):
        selected_project_id = st.selectbox(
            "项目",
            project_ids,
            index=project_ids.index(default_project),
            format_func=lambda value: next(
                item.name for item in projects if item.project_id == value
            ),
            key="task_project",
        )
        selected_project = next(
            item for item in projects if item.project_id == selected_project_id
        )
        source_kind = selected_project.source_kind
        st.caption(
            f"数据源：{_source_label(source_kind)} · 规则包："
            f"{_scenario_label(selected_project.scenario_profile)}"
        )
        goal = st.text_area(
            "审核目标",
            value=(
                "调查换型或视觉方案变化后的 NG 异常；资格化多源证据并按缺口动态补证，"
                "若责任未关闭则保持 HOLD，交付可追溯整改与独立复验条件。"
            ),
            height=105,
            key="task_goal",
        )
        c1, c2 = st.columns(2)
        seed = int(
            c1.number_input(
                "固定抽样种子",
                min_value=0,
                max_value=99_999_999,
                value=20_260_825,
                step=1,
                key="task_seed",
            )
        )
        c2.text_input(
            "规则包",
            value=_scenario_label(selected_project.scenario_profile),
            disabled=True,
        )
        plan_approval_required = st.checkbox(
            "运行前先审核 Agent 计划",
            value=source_kind is DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY,
            key="task_plan_approval_required",
            help=(
                "先展示确定性计划、工具权限和人工边界；批准前不会读取数据或调用工具。"
            ),
        )
        source_id: str | None = None
        can_submit = True
        if source_kind is DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY:
            sources = [
                item
                for item in SERVICE.list_local_source_authorizations(
                    user.user_id, selected_project.workspace_id
                )
                if item.status == "active"
            ]
            if sources:
                source_id = st.selectbox(
                    "已授权数据源",
                    [item.source_id for item in sources],
                    format_func=lambda value: next(
                        (
                            f"{item.display_name} · "
                            f"{item.data_profile.get('source_image_count', 0)} 张图像"
                        )
                        for item in sources
                        if item.source_id == value
                    ),
                    key="task_source_id",
                )
                st.info(
                    "任务只绑定脱敏 source_id；执行前会重新计算源 profile，"
                    "发生漂移即停止。"
                )
            else:
                st.warning("当前工作区尚无有效授权数据源，请先到“数据源”页面完成授权。")
                can_submit = False
            selected_tools = tools
            st.caption("执行 5 个静态只读工具，并由 Leader 按证据有界增派补证 Worker。")
        else:
            selected_tools = st.multiselect(
                "检查能力",
                tools,
                default=tools,
                format_func=_tool_label,
                key="task_allowed_tools",
            )
            can_submit = bool(selected_tools)
        submitted = st.form_submit_button(
            ("创建并等待计划审核" if plan_approval_required else "创建并运行审核任务"),
            type="primary",
            width="stretch",
            disabled=not can_submit,
        )
    if submitted:
        try:
            task = SERVICE.create_task(
                user.user_id,
                CreateTaskRequest(
                    project_id=selected_project_id,
                    goal=goal,
                    seed=seed,
                    scenario_profile=selected_project.scenario_profile,
                    source_kind=source_kind,
                    source_id=source_id,
                    plan_approval_required=plan_approval_required,
                    allowed_tools=selected_tools,
                ),
                auto_start=True,
            )
        except (ValidationError, ProductStoreError, ProductServiceError) as error:
            st.error(f"任务未创建：{str(error)[:240]}")
        else:
            st.session_state["selected_task_id"] = task.task_id
            st.session_state["_pending_nav"] = "审核记录"
            st.success(
                (
                    f"任务已创建，等待计划审核：{task.task_id}"
                    if task.plan_approval_required
                    else f"任务已进入运行队列：{task.task_id}"
                )
            )
            _rerun()


def _render_overview(
    user: Any, workspace: Any, projects: list[Any], project: Any | None
) -> None:
    tasks = SERVICE.list_tasks(
        user.user_id,
        workspace_id=workspace.workspace_id if workspace else None,
        limit=100,
    )
    completed = sum(
        task.execution_status is TaskExecutionStatus.COMPLETED for task in tasks
    )
    active = sum(
        task.execution_status
        in {
            TaskExecutionStatus.PLANNED,
            TaskExecutionStatus.RUNNING,
            TaskExecutionStatus.VERIFYING,
        }
        for task in tasks
    )
    decisions = Counter(task.final_decision for task in tasks if task.final_decision)
    external_result, external_receipt = _load_external_gate_result()
    real_task_count = sum(
        task.source_kind is DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY for task in tasks
    )
    evidence_state = (
        "受控真实证据已挂载"
        if external_result
        else ("真实授权数据任务可用" if real_task_count else "演示工作区")
    )
    st.markdown(
        f"""
<section class="vg-hero">
  <div><div class="vg-kicker">中小制造换型异常处置与复验 Agent</div><h1>把换型后 NG 异常<br>变成可复核的处置闭环</h1><p>面向质量负责人，把视觉样本、方案版本、离线运行回执与只读过程证据汇入同一案件；Agent 按证据缺口动态补证，人工批准后生成派生版本并由 child Run 独立复验。</p></div>
  <div class="vg-hero-side"><small>当前工作区</small><b>{_e(workspace.name if workspace else "尚未创建")}</b><span>{len(projects)} 个项目 · {len(tasks)} 次运行 · {_e(evidence_state)}</span></div>
</section>
""",
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="vg-head"><h2>证据中枢</h2><span>演示运行与受控真实证据分开标识</span></div>',
        unsafe_allow_html=True,
    )
    _render_external_gate_panel(external_result, external_receipt)
    st.markdown(
        '<div class="vg-head"><h2>工作区概览</h2><span>状态来自本地持久化任务</span></div>',
        unsafe_allow_html=True,
    )
    values = [
        ("项目", len(projects)),
        ("运行完成", completed),
        ("进行中", active),
        ("规则通过", decisions.get("PASS", 0)),
    ]
    st.markdown(
        '<div class="vg-metrics-grid">'
        + "".join(_metric(label, value) for label, value in values)
        + "</div>",
        unsafe_allow_html=True,
    )
    left, right = st.columns([1.35, 0.85], gap="large")
    with left:
        _render_task_form(user, projects, project)
    with right:
        st.markdown(
            '<div class="vg-head"><h2>开发者入口</h2><span>REST API</span></div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="vg-card"><small>本机可调用</small><h3>从 API 文档开始</h3><p>复制带当前用户与项目 ID 的请求；工作台和 API 共用 SQLite、服务层及不可变任务证据。</p></div>',
            unsafe_allow_html=True,
        )
        st.caption("完整请求示例、状态查询与证据下载契约见“API 接入”。")
    st.markdown(
        '<div class="vg-head"><h2>接入方式</h2><span>同一 Runtime · 同一证据契约</span></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        """
<div class="vg-entry-grid">
  <article class="vg-entry"><small>WORKSPACE</small><h3>团队工作台</h3><p>数据团队在浏览器中创建审核任务、查看问题与整改结果，并下载完整审核凭证。</p><code>人工发起 · 可视复核</code></article>
  <article class="vg-entry"><small>AGENT API</small><h3>企业 Agent 调用</h3><p>上游 Agent 通过幂等 API 提交目标和能力白名单，再按任务 ID 获取状态与 trace。</p><code>POST /v1/tasks</code></article>
  <article class="vg-entry"><small>SAAS / PIPELINE</small><h3>业务系统嵌入</h3><p>SaaS、数据平台或 CI 流水线复用同一服务层，下载 SHA-256 校验的 evidence ZIP。</p><code>GET /trace · /evidence</code></article>
</div>
""",
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="vg-head"><h2>最近运行</h2><span>最多显示 3 条</span></div>',
        unsafe_allow_html=True,
    )
    if not tasks:
        st.info("还没有运行记录。创建第一条审核任务即可开始。")
    else:
        for task in tasks[:3]:
            _task_card(task)


def _render_projects(user: Any, workspace: Any, projects: list[Any]) -> None:
    st.title("项目")
    st.caption("用项目隔离规则包、数据源和运行记录。")
    left, right = st.columns([1.35, 0.65], gap="large")
    with left:
        st.markdown(
            '<div class="vg-head"><h2>当前项目</h2><span>工作区内可见</span></div>',
            unsafe_allow_html=True,
        )
        if not projects:
            st.info("当前工作区没有项目。")
        for item in projects:
            count = len(SERVICE.list_tasks(user.user_id, project_id=item.project_id))
            st.markdown(
                f'<div class="vg-card"><small>{_e(_source_label(item.source_kind))} · {_e(_scenario_label(item.scenario_profile))}</small><h3>{_e(item.name)}</h3><p>{_e(item.description or "尚未填写项目说明")} · {count} 次运行</p></div>',
                unsafe_allow_html=True,
            )
            if st.button("设为当前项目", key=f"select_project_{item.project_id}"):
                st.session_state["active_project_id"] = item.project_id
                st.success(f"已切换到 {item.name}")
    with right:
        st.markdown(
            '<div class="vg-head"><h2>新建项目</h2><span>本地持久化</span></div>',
            unsafe_allow_html=True,
        )
        with st.form("create_project_form"):
            name = st.text_input("项目名称", key="new_project_name")
            description = st.text_area(
                "项目说明", height=90, key="new_project_description"
            )
            source_kind = st.selectbox(
                "项目数据源",
                [
                    DataSourceKind.SYNTHETIC_DEMO,
                    DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY,
                ],
                format_func=_source_label,
                key="new_project_source_kind",
                help="数据源类型在项目创建后冻结，避免任务运行时静默换源。",
            )
            submitted = st.form_submit_button(
                "创建项目", type="primary", width="stretch"
            )
        if submitted:
            try:
                created = SERVICE.create_project(
                    user.user_id,
                    CreateProjectRequest(
                        workspace_id=workspace.workspace_id,
                        name=name,
                        description=description,
                        scenario_profile=ScenarioProfile.INDUSTRIAL,
                        source_kind=source_kind,
                    ),
                )
            except (ValidationError, ProductStoreError) as error:
                st.error(f"项目未创建：{str(error)[:220]}")
            else:
                st.session_state["active_project_id"] = created.project_id
                _rerun()
        with st.expander("添加本地演示用户与工作区"):
            with st.form("create_tenant_form"):
                display_name = st.text_input("用户名称", key="new_user_name")
                workspace_name = st.text_input("工作区名称", key="new_workspace_name")
                tenant_submit = st.form_submit_button("创建用户与工作区")
            if tenant_submit:
                try:
                    new_user = SERVICE.create_user(
                        CreateUserRequest(display_name=display_name)
                    )
                    new_workspace = SERVICE.create_workspace(
                        CreateWorkspaceRequest(
                            name=workspace_name, owner_user_id=new_user.user_id
                        )
                    )
                except (ValidationError, ProductStoreError) as error:
                    st.error(f"未创建：{str(error)[:220]}")
                else:
                    st.session_state["active_user_id"] = new_user.user_id
                    st.session_state["active_workspace_id"] = new_workspace.workspace_id
                    _rerun()


def _render_data_sources(user: Any, workspace: Any) -> None:
    st.title("数据源")
    st.caption(
        "授权服务器允许目录中的工业数据；产品任务只暴露 source_id 与脱敏 profile。"
    )
    flash = st.session_state.pop("source_authorization_flash", None)
    if flash:
        st.success(flash)
    health = SERVICE.health()
    local_state = health.data_sources.get(
        DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY.value, "not_connected"
    )
    allowlist_ready = local_state == "connected_readonly_allowlist"
    sources = SERVICE.list_local_source_authorizations(
        user.user_id, workspace.workspace_id
    )
    c1, c2, c3 = st.columns(3)
    c1.metric("有效授权", sum(item.status == "active" for item in sources))
    c2.metric("目录策略", "只读允许列表" if allowlist_ready else "未配置")
    c3.metric("原始数据外发", "禁止")

    st.markdown(
        '<div class="vg-head"><h2>已授权来源</h2><span>路径与类别名不在业务界面展示</span></div>',
        unsafe_allow_html=True,
    )
    if not sources:
        st.info("当前工作区还没有授权数据源。")
    for source in sources:
        profile = source.data_profile
        status_tone = "ok" if source.status == "active" else "warn"
        st.markdown(
            f"""
<section class="vg-live">
  <div class="vg-live-top">
    <div><div class="vg-eyebrow">AUTHORIZED · READ ONLY</div><h3>{_e(source.display_name)}</h3><p>{_e(source.purpose)}</p></div>
    <span class="vg-status {status_tone}"><i class="vg-dot"></i>{_e(source.status)}</span>
  </div>
  <div class="vg-live-grid">
    <div class="vg-live-stat"><small>图像</small><b>{_e(profile.get("source_image_count", 0))}</b></div>
    <div class="vg-live-stat"><small>Mask</small><b>{_e(profile.get("source_mask_count", 0))}</b></div>
    <div class="vg-live-stat"><small>类别</small><b>{_e(profile.get("category_count", 0))}</b></div>
    <div class="vg-live-stat"><small>元数据漂移</small><b>{_e(profile.get("metadata_count_delta_total", 0))}</b></div>
    <div class="vg-live-stat"><small>再分发</small><b>禁止</b></div>
  </div>
  <div class="vg-live-hash">Source ID · {_e(source.source_id)} · Profile SHA-256 · {_e(str(profile.get("profile_sha256", ""))[:20])}…</div>
</section>
""",
            unsafe_allow_html=True,
        )
        with st.expander(
            f"授权生命周期 · {source.latest_authorization_event_type.value}",
            expanded=False,
        ):
            try:
                events = SERVICE.list_source_authorization_events(
                    user.user_id, source.source_id
                )
            except (
                ProductServiceError,
                ProductStoreError,
                OSError,
                ValueError,
            ) as error:
                st.error(f"授权事件链不可验证：{str(error)[:200]}")
                events = []
            if events:
                st.dataframe(
                    [
                        {
                            "序号": item.sequence,
                            "事件": item.event_type.value,
                            "执行者": "系统"
                            if item.actor_kind == "system"
                            else "具名操作员",
                            "生效时间": item.effective_at,
                            "失败关闭任务": len(item.fail_closed_task_ids),
                            "事件 SHA": item.event_sha256[:16],
                        }
                        for item in events
                    ],
                    hide_index=True,
                    width="stretch",
                )
            st.caption(
                f"有效期：{source.authorization_valid_until or '直到具名撤销'} · "
                f"脱敏回执保留 {source.redacted_receipt_retention_days} 天 · "
                f"派生产物保留 {source.derived_artifact_retention_days} 天。"
            )
            st.caption(
                "撤销会阻断新任务并让待运行任务失败关闭，但不会声称已删除由操作者管理的原始字节；"
                "原始数据仍禁止再分发。"
            )
            if source.status == "active":
                revoke_reason = st.text_area(
                    "撤销原因",
                    value="撤回该来源对当前工作区的一切后续执行授权。",
                    key=f"revoke_reason_{source.source_id}",
                )
                revoke_confirm = st.checkbox(
                    "我确认撤销后旧批准失效，绑定该来源的待运行任务将失败关闭。",
                    key=f"revoke_confirm_{source.source_id}",
                )
                if st.button(
                    "撤销后续执行授权",
                    disabled=not revoke_confirm,
                    key=f"revoke_source_{source.source_id}",
                    width="stretch",
                ):
                    try:
                        event = SERVICE.revoke_local_source_authorization(
                            user.user_id,
                            source.source_id,
                            RevokeLocalSourceAuthorizationRequest(
                                reason=revoke_reason,
                                expected_latest_event_sha256=(
                                    source.latest_authorization_event_sha256
                                ),
                            ),
                        )
                    except (
                        ValidationError,
                        ProductServiceError,
                        ProductStoreError,
                        OSError,
                        ValueError,
                    ) as error:
                        st.error(f"授权未撤销：{str(error)[:240]}")
                    else:
                        st.session_state["source_authorization_flash"] = (
                            f"授权已撤销；{len(event.fail_closed_task_ids)} 个待运行任务已失败关闭。"
                        )
                        _rerun()

    st.markdown(
        '<div class="vg-head"><h2>授权本地来源</h2><span>服务器路径仅作输入，不进入公开回执</span></div>',
        unsafe_allow_html=True,
    )
    if not allowlist_ready:
        st.warning(
            "服务器尚未配置本地数据允许目录，授权入口已失败关闭。"
            "管理员需先设置 VISIONDATA_LOCAL_SOURCE_ALLOW_ROOTS。"
        )
        return
    with st.form("authorize_local_source_form", clear_on_submit=False):
        display_name = st.text_input("数据源名称", value="本地工业数据源")
        root_path = st.text_input(
            "服务器本地目录",
            type="password",
            help="仅用于服务器 allowlist 校验；公开回执只保留路径哈希。",
        )
        archive_sha256 = st.text_input(
            "来源归档 SHA-256",
            max_chars=64,
            help="绑定操作员提供的来源身份；目录 profile 另行计算并在执行前复核。",
        )
        purpose = st.text_area(
            "使用目的",
            value="验证工业视觉训练数据发布前的只读质量门禁、动态补证、裁决与证据交付闭环。",
            height=85,
        )
        rights_basis = st.text_area(
            "权利与使用依据",
            value="",
            placeholder="请由操作者填写实际来源、许可或授权依据；系统不会代填或推定权利状态。",
            height=85,
        )
        validity = st.selectbox(
            "授权有效期",
            ["直到具名撤销", "30 天", "90 天", "365 天"],
            index=0,
            help="到期后系统追加 EXPIRED 事件，并在读取数据前失败关闭待运行任务。",
        )
        retention_columns = st.columns(2)
        receipt_retention_days = retention_columns[0].selectbox(
            "脱敏审计回执保留",
            [365, 3650],
            index=1,
            format_func=lambda value: f"{value} 天",
        )
        derived_retention_days = retention_columns[1].selectbox(
            "私有派生产物保留",
            [30, 90, 180, 365],
            index=1,
            format_func=lambda value: f"{value} 天",
        )
        attested = st.checkbox(
            "我确认该用途已获授权，并理解本回执不等同于法律所有权、客户验收或生产批准。"
        )
        submitted = st.form_submit_button(
            "校验并授权数据源", type="primary", width="stretch"
        )
    if submitted:
        if not attested:
            st.error("必须完成操作员授权声明；系统不会代替权利主体作出确认。")
            return
        if len(rights_basis.strip()) < 8:
            st.error(
                "请填写具体的权利与使用依据（至少 8 个字符）；系统不会根据文件存在自动推定授权。"
            )
            return
        try:
            validity_days = {
                "30 天": 30,
                "90 天": 90,
                "365 天": 365,
            }.get(validity)
            valid_until = (
                (datetime.now(UTC) + timedelta(days=validity_days)).isoformat(
                    timespec="milliseconds"
                )
                if validity_days is not None
                else None
            )
            receipt = SERVICE.authorize_local_source(
                user.user_id,
                AuthorizeLocalSourceRequest(
                    workspace_id=workspace.workspace_id,
                    display_name=display_name,
                    root_path=root_path,
                    source_archive_sha256=archive_sha256,
                    purpose=purpose,
                    rights_basis=rights_basis,
                    operator_attests_authorized_use=True,
                    authorization_valid_until=valid_until,
                    redacted_receipt_retention_days=receipt_retention_days,
                    derived_artifact_retention_days=derived_retention_days,
                ),
            )
        except (ValidationError, ProductServiceError, OSError, ValueError) as error:
            st.error(f"数据源未授权：{str(error)[:260]}")
        else:
            st.session_state["source_authorization_flash"] = (
                f"已生成脱敏授权回执：{receipt.source_id}"
            )
            _rerun()


def _timeline(status: TaskExecutionStatus) -> str:
    if status is TaskExecutionStatus.CANCELLED:
        return (
            '<div class="vg-timeline">'
            '<div class="vg-step done"><small>01</small><b>已创建</b></div>'
            '<div class="vg-step done"><small>02</small><b>已规划</b></div>'
            '<div class="vg-step current"><small>03</small><b>已取消</b></div>'
            "</div>"
        )
    steps = [
        ("CREATED", "已创建"),
        ("PLANNED", "已规划"),
        ("RUNNING", "检查中"),
        ("VERIFYING", "复验中"),
        ("COMPLETED", "已交付"),
    ]
    order = {name: index for index, (name, _) in enumerate(steps)}
    current = order.get(status.value, 4 if status is TaskExecutionStatus.FAILED else 0)
    blocks = []
    for index, (name, label) in enumerate(steps):
        tone = "done" if index < current else ("current" if index == current else "")
        blocks.append(
            f'<div class="vg-step {tone}"><small>{index + 1:02d}</small><b>{_e(label)}</b></div>'
        )
    return '<div class="vg-timeline">' + "".join(blocks) + "</div>"


def _intervention_label(action: TaskInterventionAction) -> str:
    return {
        TaskInterventionAction.APPROVE_PLAN: "批准计划",
        TaskInterventionAction.CANCEL_PLAN: "取消计划",
        TaskInterventionAction.ACKNOWLEDGE_RESULT: "确认已审阅",
        TaskInterventionAction.REQUEST_CHANGES: "要求修改",
    }[action]


def _render_task_governance(user: Any, task: Any) -> bool:
    """Render plan and human interventions; return True when execution must stop."""

    preflight = None
    try:
        preview = SERVICE.task_plan_preview(user.user_id, task.task_id)
        interventions = SERVICE.list_interventions(user.user_id, task.task_id)
        if task.execution_status is TaskExecutionStatus.PLANNED:
            preflight = SERVICE.task_preflight(user.user_id, task.task_id)
    except (ProductServiceError, ProductStoreError, OSError, ValueError) as error:
        st.error(f"计划审计不可用：{str(error)[:240]}")
        return task.execution_status in {
            TaskExecutionStatus.PLANNED,
            TaskExecutionStatus.CANCELLED,
        }

    st.markdown(
        '<div class="vg-head"><h2>任务控制与人工边界</h2>'
        "<span>计划可审 · 干预留痕 · 生产审批不交给 Agent</span></div>",
        unsafe_allow_html=True,
    )
    with st.expander(
        "查看执行计划与工具权限",
        expanded=(task.execution_status is TaskExecutionStatus.PLANNED),
    ):
        st.dataframe(
            [
                {
                    "阶段": step.phase,
                    "责任 Agent": step.agent_role,
                    "计划动作": step.objective,
                    "允许工具": "、".join(_tool_label(name) for name in step.tool_names)
                    or "无",
                    "人工节点": "是" if step.human_gate else "否",
                }
                for step in preview.steps
            ],
            hide_index=True,
            width="stretch",
        )
        st.caption(preview.dynamic_replanning_policy)
        st.code(f"Plan SHA-256  {preview.plan_sha256}", language=None)
        st.caption(preview.claim_boundary)

    if preflight is not None:
        preflight_labels = {
            "READY_TO_RUN": "运行条件已满足",
            "AWAITING_HUMAN_APPROVAL": "等待人工计划批准",
            "BLOCKED": "运行前置条件未满足",
            "NOT_RUNNABLE": "当前状态不可运行",
        }
        message = (
            f"运行前就绪门禁：{preflight_labels[preflight.overall_status]}。"
            "数据快照、工具白名单与权限边界均在批准前独立核验。"
        )
        if preflight.prerequisite_ready:
            st.info(message)
        else:
            st.error(message)
        st.dataframe(
            [
                {
                    "检查项": item.label,
                    "状态": item.status,
                    "说明": item.summary,
                    "证据": item.evidence_ref,
                    "SHA": (item.evidence_sha256 or "")[:12] or "—",
                }
                for item in preflight.checks
            ],
            hide_index=True,
            width="stretch",
        )
        st.download_button(
            "下载运行前就绪报告 JSON",
            canonical_json_bytes(preflight),
            file_name=f"{task.task_id}-preflight.json",
            mime="application/json",
            key=f"preflight_{task.task_id}",
            width="stretch",
        )

    if interventions:
        st.dataframe(
            [
                {
                    "序号": item.sequence,
                    "操作": _intervention_label(item.action),
                    "变更前状态": item.before_status.value,
                    "说明": item.note,
                    "快照": item.before_snapshot_sha256[:12],
                    "时间": item.created_at[:19].replace("T", " "),
                }
                for item in interventions
            ],
            hide_index=True,
            width="stretch",
        )
        st.caption("干预记录仅追加；每条记录绑定操作前任务快照与同一计划哈希。")

    if task.execution_status is TaskExecutionStatus.CANCELLED:
        st.info("该计划已在任何工具调用前取消；没有生成运行结果或证据包。")
        return True

    if (
        task.execution_status is TaskExecutionStatus.PLANNED
        and task.plan_approval_required
    ):
        st.warning("当前只生成了计划预览。批准前不会读取数据、调用工具或生成裁决。")
        note = st.text_input(
            "本次计划审核说明",
            value="已核对数据范围、工具权限、补证边界和人工最终审批节点。",
            key=f"plan_review_note_{task.task_id}",
        )
        approve_col, cancel_col = st.columns(2)
        approve = approve_col.button(
            "批准并开始运行",
            type="primary",
            width="stretch",
            key=f"approve_plan_{task.task_id}",
            disabled=(preflight is not None and not preflight.prerequisite_ready),
        )
        cancel = cancel_col.button(
            "取消本次计划",
            width="stretch",
            key=f"cancel_plan_{task.task_id}",
        )
        action = None
        if approve:
            action = TaskInterventionAction.APPROVE_PLAN
        elif cancel:
            action = TaskInterventionAction.CANCEL_PLAN
        if action is not None:
            try:
                SERVICE.intervene_task(
                    user.user_id,
                    task.task_id,
                    TaskInterventionRequest(action=action, note=note),
                )
            except (
                ValidationError,
                ProductServiceError,
                ProductStoreError,
                OSError,
                ValueError,
            ) as error:
                st.error(f"人工操作未记录：{str(error)[:240]}")
            else:
                _rerun()
        return True

    if task.execution_status is TaskExecutionStatus.COMPLETED:
        result_reviews = [
            item
            for item in interventions
            if item.action
            in {
                TaskInterventionAction.ACKNOWLEDGE_RESULT,
                TaskInterventionAction.REQUEST_CHANGES,
            }
        ]
        if not result_reviews:
            note = st.text_input(
                "结果审阅说明",
                value="已核对最终裁决、证据引用、工单和安全边界。",
                key=f"result_review_note_{task.task_id}",
            )
            accept_col, revise_col = st.columns(2)
            accept = accept_col.button(
                "确认已审阅",
                width="stretch",
                key=f"acknowledge_result_{task.task_id}",
            )
            revise = revise_col.button(
                "要求修改",
                width="stretch",
                key=f"request_changes_{task.task_id}",
            )
            action = None
            if accept:
                action = TaskInterventionAction.ACKNOWLEDGE_RESULT
            elif revise:
                action = TaskInterventionAction.REQUEST_CHANGES
            if action is not None:
                try:
                    SERVICE.intervene_task(
                        user.user_id,
                        task.task_id,
                        TaskInterventionRequest(action=action, note=note),
                    )
                except (
                    ValidationError,
                    ProductServiceError,
                    ProductStoreError,
                    OSError,
                    ValueError,
                ) as error:
                    st.error(f"结果审阅未记录：{str(error)[:240]}")
                else:
                    _rerun()
        else:
            latest = result_reviews[-1]
            st.success(f"结果审阅已留痕：{_intervention_label(latest.action)}。")
    return False


def _load_task_payload(
    user: Any, task: Any, relative_path: str
) -> dict[str, Any] | None:
    try:
        return SERVICE.read_evidence_zip_json(user.user_id, task.task_id, relative_path)
    except (ArtifactUnavailableError, json.JSONDecodeError):
        return None


def _load_task_csv(user: Any, task: Any, relative_path: str) -> list[dict[str, str]]:
    try:
        payload = SERVICE.read_evidence_zip_bytes(
            user.user_id, task.task_id, relative_path
        )
        return list(csv.DictReader(io.StringIO(payload.decode("utf-8-sig"))))
    except (ArtifactUnavailableError, UnicodeDecodeError, csv.Error):
        return []


def _render_evidence_chain(user: Any, task: Any) -> None:
    is_local_source = task.source_kind is DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY
    if is_local_source:
        initial_rows = _load_task_csv(user, task, "evidence_matrix.csv")
        repaired_rows: list[dict[str, str]] = []
        initial_result = _load_task_payload(user, task, "final/gate_result.json") or {}
    else:
        initial_rows = _load_task_csv(user, task, "initial/evidence_matrix.csv")
        repaired_rows = _load_task_csv(user, task, "repaired/evidence_matrix.csv")
        initial_result = (
            _load_task_payload(user, task, "initial/gate_result.json") or {}
        )
    if not initial_rows:
        st.info("当前凭证没有可展示的证据链记录。")
        return
    repaired_codes = {
        row.get("finding_code", "") for row in repaired_rows if row.get("finding_code")
    }
    finding_by_id = {
        item.get("finding_id", ""): item
        for item in initial_result.get("findings", [])
        if item.get("finding_id")
    }
    order_by_id = {
        item.get("work_order_id", ""): item
        for item in initial_result.get("work_orders", [])
        if item.get("work_order_id")
    }
    cards = []
    rows_by_code: dict[str, list[dict[str, str]]] = {}
    for row in initial_rows:
        rows_by_code.setdefault(row.get("finding_code", ""), []).append(row)
    for finding_code, matrix_rows in rows_by_code.items():
        row = matrix_rows[0]
        finding_ids = list(
            dict.fromkeys(
                item.get("finding_id", "")
                for item in matrix_rows
                if item.get("finding_id")
            )
        )
        order_ids = list(
            dict.fromkeys(
                order_id
                for item in matrix_rows
                for order_id in item.get("work_order_ids", "").split("|")
                if order_id
            )
        )
        orders = [order_by_id.get(order_id, {}) for order_id in order_ids]
        sample_ids = sorted(
            {
                sample_id
                for finding_id in finding_ids
                for sample_id in finding_by_id.get(finding_id, {}).get("sample_ids", [])
            }
            | {
                sample_id
                for item in matrix_rows
                for sample_id in item.get("sample_ids", "").split("|")
                if sample_id
            }
        )
        actions = list(
            dict.fromkeys(
                _action_label(order.get("action", ""))
                for order in orders
                if order.get("action")
            )
        )
        if is_local_source:
            recheck = "已绑定最终裁决"
            recheck_tone = "warn"
        else:
            recheck = "仍需处理" if finding_code in repaired_codes else "复验已消除"
            recheck_tone = "warn" if finding_code in repaired_codes else "ok"
        cards.append(
            f"""
<article class="vg-evidence-item">
  <div class="vg-evidence-top"><small>{_e(_tool_label(row.get("tool", "")))}</small><span class="vg-status {recheck_tone}"><i class="vg-dot"></i>{_e(recheck)}</span></div>
  <h3>{_e(_finding_label(finding_code))}</h3>
  <p><b>影响范围</b> · {_e(f"{len(finding_ids)} 条 finding · {len(sample_ids)} 个脱敏对象" if sample_ids else f"{len(finding_ids)} 条批次级 finding")}</p>
  <p><b>整改动作</b> · {_e("、".join(actions) if actions else "按工单处理")} · {_e(len(order_ids))} 张关联工单</p>
</article>
"""
        )
    st.markdown(
        '<div class="vg-evidence-grid">' + "".join(cards) + "</div>",
        unsafe_allow_html=True,
    )
    st.caption(
        "以上映射来自已验 SHA-256 的 evidence ZIP；完整 finding ID、evidence_span、"
        "reason_trace 与规则检查保留在下载凭证和高级审计中。"
    )


def _render_dynamic_followups(user: Any, task: Any) -> None:
    plan = _load_task_payload(user, task, "dynamic_leader_plan.json")
    if plan is None:
        st.info("当前任务没有动态补证计划。")
        return
    budget = plan.get("followup_budget", {})
    metrics = st.columns(4)
    metrics[0].metric("静态工具", plan.get("static_task_count", 0))
    metrics[1].metric("动态 Worker", plan.get("dynamic_task_count", 0))
    metrics[2].metric("重规划", plan.get("replan_count", 0))
    metrics[3].metric(
        "补证预算",
        f"{budget.get('consumed_units', 0)}/{budget.get('budget_limit_units', 0)}",
    )
    labels = {
        "followup.metadata-reconciliation": {
            "title": "元数据总量独立复核",
            "trigger": "首轮证据发现元数据记录总量与目录实测不一致",
            "effect": "保留调查工单，禁止自动修补元数据",
            "stop": "独立重扫一次目录与元数据后停止",
        },
        "followup.native-resolution-reconciliation": {
            "title": "原生分辨率分组复查",
            "trigger": "接入阶段发现多个原生分辨率组",
            "effect": "仅在各分辨率组复查结果一致时接受质量证据",
            "stop": "每个入选原生分辨率组完成一次独立复查后停止",
        },
        "followup.cross-tool-conflict-adjudication": {
            "title": "跨工具工单冲突裁决",
            "trigger": "首轮裁决发现同一对象关联多个处置动作",
            "effect": "先转人工调查，再按安全顺序执行整改",
            "stop": "完成 finding 到工单的链接复核与动作排序后停止",
        },
    }
    cards: list[str] = []
    for item in plan.get("dynamic_tasks", []):
        status = str(item.get("status", "unknown"))
        tone = "ok" if status == "completed" else "fail"
        task_id = str(item.get("task_id", ""))
        presentation = labels.get(
            task_id,
            {
                "title": task_id,
                "trigger": str(item.get("trigger", "")),
                "effect": str(item.get("decision_effect", "")),
                "stop": str(item.get("stop_condition", "")),
            },
        )
        status_label = {
            "completed": "已完成",
            "failed": "执行失败",
            "budget_exhausted": "预算不足",
        }.get(status, status)
        cards.append(
            f"""
<article class="vg-evidence-item">
  <div class="vg-evidence-top"><small>第 {_e(item.get("dispatch_index", "—"))} 个补证任务</small><span class="vg-status {tone}"><i class="vg-dot"></i>{_e(status_label)}</span></div>
  <h3>{_e(presentation["title"])}</h3>
  <p><b>触发依据</b> · {_e(presentation["trigger"])}</p>
  <p><b>裁决作用</b> · {_e(presentation["effect"])}</p>
  <p><b>停止条件</b> · {_e(presentation["stop"])}</p>
  <p><b>证据哈希</b> · {_e(str(item.get("tool_trace_result_sha256", ""))[:20])}…</p>
</article>
"""
        )
    st.markdown(
        '<div class="vg-evidence-grid">' + "".join(cards) + "</div>",
        unsafe_allow_html=True,
    )
    st.caption(
        "Leader 在首轮 Judge 后依据已出现的证据竞价派发；每个 Worker 都执行新的"
        "只读工具调用并绑定输入/输出 SHA，而不是固定 DAG 的别名回执。"
    )
    st.code(
        "Semantic plan SHA-256  "
        + str(plan.get("semantic_dispatch_plan_sha256", "unavailable")),
        language=None,
    )


def _render_industrial_delivery(user: Any, task: Any) -> None:
    try:
        receipt = SERVICE.industrial_delivery_receipt(user.user_id, task.task_id)
        readiness = SERVICE.task_release_readiness(user.user_id, task.task_id)
    except (ArtifactUnavailableError, ProductServiceError, OSError, ValueError):
        st.info("当前历史证据包未包含工业交付回执；新运行会按当前合同生成。")
        return

    readiness_labels = {
        "READY_FOR_HUMAN_REVIEW": "可进入人工计划复核",
        "BLOCKED_GATE_DECISION": "门禁阻断，等待整改复验",
        "BLOCKED_SOURCE_STALE": "输入已变化，旧裁决失效",
        "BLOCKED_EVIDENCE_INTEGRITY": "证据完整性异常",
        "DEMO_ONLY": "仅限演示，不可生产放行",
    }
    freshness_labels = {
        "CURRENT": "当前",
        "STALE": "已过期",
        "UNAVAILABLE": "不可验证",
        "NOT_APPLICABLE": "不适用",
    }
    readiness_message = (
        f"发布就绪门禁：{readiness_labels[readiness.overall_status]}。"
        f"{readiness.required_human_action}"
    )
    if readiness.overall_status == "READY_FOR_HUMAN_REVIEW":
        st.success(readiness_message)
    elif readiness.overall_status in {
        "BLOCKED_SOURCE_STALE",
        "BLOCKED_EVIDENCE_INTEGRITY",
    }:
        st.error(readiness_message)
    else:
        st.warning(readiness_message)
    readiness_metrics = st.columns(3)
    readiness_metrics[0].metric(
        "输入快照", freshness_labels[readiness.source_freshness]
    )
    readiness_metrics[1].metric("证据包", readiness.evidence_integrity)
    readiness_metrics[2].metric(
        "未闭环工单",
        readiness.open_work_order_count
        if readiness.open_work_order_count is not None
        else "不可确认",
    )
    with st.expander("查看发布就绪检查", expanded=False):
        st.dataframe(
            [
                {
                    "检查项": item.label,
                    "状态": item.status,
                    "说明": item.summary,
                    "证据": item.evidence_ref,
                    "SHA": (item.evidence_sha256 or "")[:12] or "—",
                }
                for item in readiness.checks
            ],
            hide_index=True,
            width="stretch",
        )
        st.caption(readiness.claim_boundary)
        st.download_button(
            "下载发布就绪报告 JSON",
            canonical_json_bytes(readiness),
            file_name=f"{task.task_id}-release-readiness.json",
            mime="application/json",
            key=f"release_readiness_{task.task_id}",
            width="stretch",
        )

    metrics = st.columns(4)
    metrics[0].metric("风险处置流", len(receipt.risk_clusters))
    metrics[1].metric("候选整改方案", len(receipt.remediation_plans))
    metrics[2].metric("原子证据记录", len(receipt.executable_work_orders))
    metrics[3].metric("生产审批", "待人工确认")
    st.caption(
        "原子证据记录用于逐条追溯，不等于同数量的 Agent 任务；用户先比较风险处置流和候选方案，"
        "任何源数据修改、设备控制与生产放行均不自动执行。"
    )
    source_labels = {
        "image_batch": "图像批次",
        "mask_annotation": "掩码与标注",
        "manifest_metadata": "清单与元数据",
        "tool_measurement": "工具测量",
        "frozen_policy": "冻结规则",
        "operator_authorization": "操作员授权",
    }
    source_roles = {
        "image_batch": "提供脱敏后的来源总体画像",
        "mask_annotation": "界定标注可用性与完整性范围",
        "manifest_metadata": "数量漂移时触发目录与元数据对账",
        "tool_measurement": "绑定工具输入、输出哈希与发现项",
        "frozen_policy": "将证据映射为失败关闭裁决和工单",
        "operator_authorization": "记录使用与驻留声明，不推定数据所有权",
    }
    status_labels = {"used": "已使用", "operator_attested": "操作员声明"}
    action_labels = {
        "RECAPTURE": "重新采集",
        "RELABEL": "重新标注",
        "REMOVE_OR_REPARTITION": "移除或重划分",
        "INVESTIGATE": "调查",
    }
    priority_labels = {
        "critical": "关键",
        "high": "高",
        "medium": "中",
        "low": "低",
    }
    expert_labels = {
        "Acquisition Quality Expert Agent": "采集质量专家 Agent",
        "Annotation Integrity Expert Agent": "标注完整性专家 Agent",
        "Dataset Leakage Governance Agent": "数据泄漏治理 Agent",
        "Industrial Root-Cause Review Agent": "工业根因复核 Agent",
    }
    skill_labels = {
        "industrial-image-acquisition-quality": "工业图像采集质量",
        "industrial-annotation-integrity": "工业标注完整性",
        "industrial-dataset-split-governance": "数据集划分治理",
        "industrial-evidence-conflict-investigation": "证据冲突调查",
    }
    owner_labels = {
        "industrial_data_owner": "工业数据责任人",
        "annotation_quality_owner": "标注质量责任人",
        "dataset_governance_owner": "数据治理责任人",
        "quality_or_safety_owner": "质量或安全责任人",
    }

    if receipt.risk_clusters:
        st.markdown("#### 风险处置流")
        st.caption(
            "系统按责任、动作与 Skill 聚合原子问题；聚合不合并证据、不自动关闭问题，也不代表全量缺陷率。"
        )
        st.dataframe(
            [
                {
                    "处置流": item.title,
                    "目标": item.objective,
                    "动作": action_labels.get(item.action, item.action),
                    "最高优先级": priority_labels.get(item.priority, item.priority),
                    "问题类型": "、".join(item.reason_codes),
                    "原子记录": item.atomic_work_order_count,
                    "涉及样本": item.affected_sample_count,
                    "责任角色": owner_labels.get(
                        item.human_owner_role, item.human_owner_role
                    ),
                    "Skill": skill_labels.get(item.required_skill, item.required_skill),
                    "自动执行": "禁止",
                    "SHA": item.cluster_sha256[:12],
                }
                for item in receipt.risk_clusters
            ],
            hide_index=True,
            width="stretch",
        )

    if receipt.remediation_plans:
        st.markdown("#### 三套候选整改方案")
        st.caption(
            "方案用于人工计划比较；相对工作量只用于本次方案排序，不是工时、金额或成功承诺。"
        )
        plan_columns = st.columns(len(receipt.remediation_plans))
        for column, plan in zip(plan_columns, receipt.remediation_plans, strict=True):
            with column.container(border=True):
                st.markdown(f"**{_e(plan.title)}**")
                st.caption(plan.objective)
                st.metric("证据覆盖", f"{plan.evidence_coverage_ratio:.0%}")
                st.markdown(
                    f"选择 **{len(plan.selected_work_order_ids)}** 条原子记录 · "
                    f"暂缓 **{len(plan.deferred_work_order_ids)}** 条"
                )
                st.markdown(f"相对工作量 **{plan.relative_effort_points} points**")
                st.markdown(f"执行波次 **{len(plan.waves)}**（末波为 child Run 复验）")
                residual = "、".join(plan.residual_risk_codes) or "无暂缓风险代码"
                st.caption(f"残余风险：{residual}")
                st.code(f"Plan SHA-256  {plan.plan_sha256}", language=None)
                st.warning(
                    "尚未执行；必须人工计划批准并由独立 child Run 按同合同复验。"
                )

    st.markdown("#### 多源信息融合")
    st.dataframe(
        [
            {
                "来源": source_labels.get(item.source_type, item.source_type),
                "观测量": item.observed_count,
                "状态": status_labels.get(item.status, item.status),
                "裁决作用": source_roles.get(item.source_type, item.role_in_decision),
                "证据": item.evidence_ref,
                "SHA": item.evidence_sha256[:12],
            }
            for item in receipt.multi_source_fusion
        ],
        hide_index=True,
        width="stretch",
    )
    with st.expander(
        f"查看 {len(receipt.executable_work_orders)} 条原子证据记录与验收合同"
    ):
        st.caption(
            "每条记录绑定 finding、工具证据和冻结规则，服务于逐条关闭与复验；它不是独立 Agent，也不是完整生产任务。"
        )
        st.dataframe(
            [
                {
                    "原子记录": item.work_order_id,
                    "动作": action_labels.get(item.action, item.action),
                    "优先级": priority_labels.get(item.priority, item.priority),
                    "AI 专家": expert_labels.get(
                        item.ai_expert_role, item.ai_expert_role
                    ),
                    "Skill": skill_labels.get(item.required_skill, item.required_skill),
                    "责任角色": owner_labels.get(
                        item.human_owner_role, item.human_owner_role
                    ),
                    "验收标准": "；".join(item.acceptance_criteria),
                    "证据数": len(item.evidence_span),
                    "自动执行": "禁止",
                }
                for item in receipt.executable_work_orders
            ],
            hide_index=True,
            width="stretch",
        )
    with st.expander("查看自治边界与未完成项"):
        st.markdown("**允许 Agent 执行**")
        for item in receipt.allowed_agent_actions:
            st.markdown(f"- {_e(item)}")
        st.markdown("**明确禁止**")
        for item in receipt.forbidden_agent_actions:
            st.markdown(f"- {_e(item)}")
        st.markdown("**仍未验证**")
        for item in receipt.unresolved_boundaries:
            st.markdown(f"- {_e(item)}")
        st.caption(receipt.claim_boundary)
    st.download_button(
        "下载工业交付回执 JSON",
        canonical_json_bytes(receipt),
        file_name=f"{task.task_id}-industrial-delivery.json",
        mime="application/json",
        key=f"industrial_delivery_{task.task_id}",
        width="stretch",
    )


def _render_capa_control(
    user: Any,
    task: Any,
    *,
    locked_case_id: str | None = None,
) -> None:
    """Operate the private evidence-driven CAPA chain without exposing source paths."""

    try:
        delivery = SERVICE.industrial_delivery_receipt(user.user_id, task.task_id)
        cases = SERVICE.list_capa_cases(user.user_id, task.task_id)
    except (ProductServiceError, ProductStoreError, OSError, ValueError) as error:
        st.info(f"当前任务尚不能创建整改闭环：{str(error)[:180]}")
        return

    if locked_case_id is not None:
        cases = [item for item in cases if item.case_id == locked_case_id]

    st.markdown(
        '<div class="vg-head"><h2>整改执行与独立复验</h2>'
        "<span>Evidence-Driven CAPA · 私有派生版本</span></div>",
        unsafe_allow_html=True,
    )
    st.caption(
        "这里执行的不是“生成工单”，而是具名选择方案、哈希批准、生成私有派生版本、"
        "启动独立 child Run，再根据复验证据关闭、阻断或转调查。父来源与父 Evidence ZIP 保持不变。"
    )

    if not cases and locked_case_id is not None:
        st.error("人工决定绑定的 CAPA Case 不存在或不可验证；已停止后续执行。")
        return

    if not cases:
        stages = [
            ("01", "父 Run", "证据已冻结"),
            ("02", "选择方案", "等待具名选择"),
            ("03", "批准", "绑定规则与授权 SHA"),
            ("04", "派生版本", "仅复制到私有空间"),
            ("05", "child Run", "同合同独立复验"),
            ("06", "责任队列", "恢复 / 阻断 / 调查"),
        ]
        st.markdown(
            '<div class="vg-loop">'
            + "".join(
                f'<div class="vg-loop-step"><small>{_e(index)}</small>'
                f"<b>{_e(title)}</b><span>{_e(detail)}</span></div>"
                for index, title, detail in stages
            )
            + "</div>",
            unsafe_allow_html=True,
        )
        st.markdown("#### 创建 CAPA Case")
        plan = st.selectbox(
            "选择整改方案",
            delivery.remediation_plans,
            format_func=lambda item: (
                f"{item.title} · 覆盖 {item.evidence_coverage_ratio:.0%} · "
                f"{len(item.selected_work_order_ids)} 条原子记录"
            ),
            key=f"capa_plan_{task.task_id}",
        )
        note = st.text_area(
            "选择依据",
            value=(
                "按风险、证据覆盖、残余风险和相对工作量选择；本次选择不等于批准执行。"
            ),
            key=f"capa_select_note_{task.task_id}",
        )
        confirm = st.checkbox(
            "我确认当前只创建方案选择记录，不修改父来源、不启动 child Run。",
            key=f"capa_select_confirm_{task.task_id}",
        )
        if st.button(
            "冻结所选方案与责任队列",
            type="primary",
            disabled=not confirm,
            key=f"capa_select_{task.task_id}",
            width="stretch",
        ):
            try:
                SERVICE.select_remediation_plan(
                    user.user_id,
                    task.task_id,
                    SelectRemediationPlanRequest(
                        plan_id=plan.plan_id,
                        plan_sha256=plan.plan_sha256,
                        note=note,
                    ),
                )
            except (
                ProductServiceError,
                ProductStoreError,
                OSError,
                ValueError,
            ) as error:
                st.error(f"方案未冻结：{str(error)[:240]}")
            else:
                st.success("方案、证据范围和初始责任队列已冻结；尚未批准或执行。")
                _rerun()
        return

    status_labels = {
        "SELECTED": "已选择，待批准",
        "APPROVED": "已批准，待执行",
        "DERIVED_VERSION_READY": "派生版本已生成",
        "CHILD_RUN_COMPLETED": "child Run 已完成",
        "RECOVERED_TO_HUMAN_REVIEW": "已恢复到人工计划复核",
        "STILL_BLOCKED": "复验后仍阻断",
        "TRANSFERRED_TO_INVESTIGATION": "已转人工调查",
    }
    if locked_case_id is not None:
        report = cases[0]
        st.caption(
            f"已锁定具名决定绑定的 CAPA Case：{report.case_id}；不可切换到其他整改案件。"
        )
    else:
        selected_case_id = st.selectbox(
            "CAPA Case",
            [item.case_id for item in cases],
            format_func=lambda case_id: (
                f"{case_id} · "
                f"{status_labels.get(next(item for item in cases if item.case_id == case_id).status.value, next(item for item in cases if item.case_id == case_id).status.value)}"
            ),
            key=f"capa_case_{task.task_id}",
        )
        report = next(item for item in cases if item.case_id == selected_case_id)
    state = report.status.value
    completed_stages = {
        "SELECTED": 2,
        "APPROVED": 3,
        "DERIVED_VERSION_READY": 4,
        "CHILD_RUN_COMPLETED": 5,
        "RECOVERED_TO_HUMAN_REVIEW": 6,
        "STILL_BLOCKED": 6,
        "TRANSFERRED_TO_INVESTIGATION": 6,
    }.get(state, 1)
    stage_rows = [
        ("父 Run", "证据冻结"),
        ("方案", "具名选择"),
        ("批准", "哈希绑定"),
        ("派生", "私有副本"),
        ("复验", "child Run"),
        ("队列", "状态交付"),
    ]
    st.markdown(
        '<div class="vg-loop">'
        + "".join(
            f'<div class="vg-loop-step"><small>{"DONE" if index <= completed_stages else "PENDING"}</small>'
            f"<b>{_e(title)}</b><span>{_e(detail)}</span></div>"
            for index, (title, detail) in enumerate(stage_rows, start=1)
        )
        + "</div>",
        unsafe_allow_html=True,
    )

    selection = report.selection
    summary = st.columns(4)
    summary[0].metric("Case 状态", status_labels.get(state, state))
    summary[1].metric("方案覆盖", f"{selection.plan.evidence_coverage_ratio:.0%}")
    summary[2].metric("纳入工单", len(selection.plan.selected_work_order_ids))
    summary[3].metric("父数据变更", "禁止")
    st.code(
        f"Selection SHA-256  {selection.selection_sha256}\n"
        f"Plan SHA-256       {selection.plan.plan_sha256}\n"
        f"Parent Evidence    {selection.parent_evidence_sha256}",
        language=None,
    )

    queue = report.final_queue or report.initial_queue
    queue_status_labels = {
        "PENDING_APPROVAL": "待批准",
        "APPROVED": "已批准",
        "EXECUTED_ON_DERIVED_VERSION": "已在派生版本执行",
        "DEFERRED_NOT_SELECTED": "本方案暂缓",
        "BLOCKED_NO_REPLACEMENT": "无合规候选，阻断",
        "AWAITING_HUMAN_INVESTIGATION": "等待人工调查",
        "VERIFIED_CLOSED": "child Run 已证实关闭",
        "RECHECK_FAILED": "复验失败",
    }
    st.markdown("#### 责任队列")
    st.dataframe(
        [
            {
                "工单": item.work_order_id,
                "动作": item.action,
                "优先级": item.priority,
                "责任角色": item.owner_role,
                "所需 Skill": item.required_skill,
                "状态": queue_status_labels.get(item.status.value, item.status.value),
                "原因": item.status_reason,
                "证据": " · ".join(item.evidence_refs[:2]),
                "结果": " · ".join(item.result_refs[:2]),
            }
            for item in queue.items
            if item.selected
        ],
        hide_index=True,
        width="stretch",
    )
    st.caption(
        f"队列 SHA-256：{queue.queue_sha256} · 未关闭 {queue.open_count} · 已关闭 {queue.closed_count}"
    )

    if report.approval is None:
        st.markdown("#### 具名批准")
        st.warning(
            "批准会绑定父 request/Evidence、工业交付、方案、规则合同、来源画像、"
            "最新授权事件和责任队列 SHA；其中任何一项变化，旧批准都失败关闭。"
        )
        approval_note = st.text_area(
            "批准说明",
            value="批准仅在私有派生版本内执行所选动作，并由独立 child Run 复验。",
            key=f"capa_approval_note_{report.case_id}",
        )
        try:
            gate_receipt = SERVICE.read_evidence_zip_json(
                user.user_id, task.task_id, "omni_gate_receipt.json"
            )
            planned_copy_count = int(gate_receipt["selected_image_count"])
        except (ProductServiceError, ProductStoreError, OSError, KeyError, ValueError):
            planned_copy_count = 1
        max_images = st.number_input(
            "允许复制到私有派生版本的图像上限",
            min_value=planned_copy_count,
            max_value=10000,
            value=max(240, planned_copy_count),
            step=1,
            key=f"capa_copy_budget_{report.case_id}",
            help=(
                f"当前 Gate 冻结选择为 {planned_copy_count} 张；预算按实际复制图像计算，"
                "不是按工单数量计算。"
            ),
        )
        attest = st.checkbox(
            "我授权本次私有派生处理；不授权修改父来源、再分发原始数据或生产放行。",
            key=f"capa_approval_attest_{report.case_id}",
        )
        if st.button(
            "批准所选方案",
            type="primary",
            disabled=not attest,
            key=f"capa_approve_{report.case_id}",
            width="stretch",
        ):
            try:
                SERVICE.approve_remediation_plan(
                    user.user_id,
                    task.task_id,
                    report.case_id,
                    ApproveRemediationPlanRequest(
                        note=approval_note,
                        approved_work_order_ids=(
                            selection.plan.selected_work_order_ids
                        ),
                        operator_attests_derived_processing=True,
                        source_mutation_permitted=False,
                        raw_redistribution_allowed=False,
                        max_copied_images=int(max_images),
                    ),
                )
            except (
                ProductServiceError,
                ProductStoreError,
                OSError,
                ValueError,
            ) as error:
                st.error(f"批准失败：{str(error)[:240]}")
            else:
                st.success("批准已写入不可变绑定；尚未生成派生版本或启动复验。")
                _rerun()
        return

    approval = report.approval
    st.markdown("#### 批准绑定")
    st.code(
        f"Approval SHA-256       {approval.binding_sha256}\n"
        f"授权事件 SHA-256       {approval.source_authorization_event_sha256 or 'legacy-missing'}\n"
        f"计划复制图像           {approval.planned_copy_count or 'legacy-unbound'} / {approval.max_copied_images}\n"
        f"Rule Contract           {approval.rule_contract_sha256}\n"
        f"Responsibility Queue    {approval.responsibility_queue_sha256}",
        language=None,
    )
    if report.execution is None:
        st.warning(
            "下一步会复制授权范围内的必要资产到私有派生版本，并同步完成 child Run。"
            "该操作不会覆盖父来源；若候选不足或复验不通过，结果会保持阻断或转调查。"
        )
        execute_confirm = st.checkbox(
            "我确认执行已批准方案并等待独立 child Run 完成。",
            key=f"capa_execute_confirm_{report.case_id}",
        )
        if st.button(
            "生成派生版本并执行 child Run",
            type="primary",
            disabled=not execute_confirm,
            key=f"capa_execute_{report.case_id}",
            width="stretch",
        ):
            try:
                with st.spinner("正在生成私有派生版本并执行同合同复验……"):
                    SERVICE.execute_remediation_plan(
                        user.user_id, task.task_id, report.case_id
                    )
            except (
                ProductServiceError,
                ProductStoreError,
                OSError,
                ValueError,
            ) as error:
                st.error(f"CAPA 执行未完成：{str(error)[:240]}")
            else:
                st.success("child Run 已结束；正在加载责任队列与恢复结论。")
                _rerun()
        return

    execution = report.execution
    derived = report.derived_version
    recovery = report.recovery
    if derived is not None:
        operation_counts = Counter(item.status for item in derived.operations)
        derived_metrics = st.columns(4)
        derived_metrics[0].metric("派生图像", derived.derived_image_count)
        derived_metrics[1].metric("已执行动作", operation_counts.get("EXECUTED", 0))
        derived_metrics[2].metric("阻断动作", operation_counts.get("BLOCKED", 0))
        derived_metrics[3].metric("回滚方式", "丢弃派生版本")
        st.caption(
            f"派生版本 {derived.version_id} · rollback {derived.rollback_point_sha256[:16]}… · "
            f"父来源变更：{'是' if derived.parent_source_mutated else '否'}"
        )
    if recovery is not None:
        comparison = st.columns(4)
        comparison[0].metric("父 Run findings", recovery.parent_finding_count)
        comparison[1].metric("child Run findings", recovery.child_finding_count)
        comparison[2].metric("证实关闭", recovery.verified_closed_work_order_count)
        comparison[3].metric("仍待处理", recovery.remaining_work_order_count)
        message = f"{status_labels.get(recovery.status, recovery.status)}。{recovery.required_human_action}"
        if recovery.recovery_success:
            st.success(message)
        elif recovery.status == "TRANSFERRED_TO_INVESTIGATION":
            st.error(message)
        else:
            st.warning(message)
        st.code(
            f"Parent Evidence  {recovery.parent_evidence_sha256}\n"
            f"Child Evidence   {recovery.child_evidence_sha256}\n"
            f"Recovery Receipt {recovery.receipt_sha256}",
            language=None,
        )
        try:
            outcome = SERVICE.capa_outcome_assessment(
                user.user_id, task.task_id, report.case_id
            )
        except (ProductServiceError, ProductStoreError, OSError, ValueError) as error:
            st.error(f"整改可行性评估不可验证：{str(error)[:220]}")
        else:
            st.markdown("#### 整改可行性与最小成本边界")
            st.dataframe(
                [
                    {
                        "方案": item.plan_id,
                        "状态": item.execution_status,
                        "覆盖": f"{item.evidence_coverage_ratio:.0%}",
                        "相对 effort": item.relative_effort_points,
                        "纳入 / 暂缓": (
                            f"{item.selected_work_order_count} / "
                            f"{item.deferred_work_order_count}"
                        ),
                        "实测 child 结论": item.observed_child_decision or "未执行",
                        "实测剩余": (
                            item.observed_remaining_work_order_count
                            if item.observed_remaining_work_order_count is not None
                            else "未执行"
                        ),
                    }
                    for item in outcome.plan_observations
                ],
                hide_index=True,
                width="stretch",
            )
            if outcome.observed_release_candidate_found:
                st.success(outcome.required_next_action)
            else:
                st.warning(
                    f"{outcome.release_feasibility_status}："
                    f"{outcome.required_next_action} 最小恢复成本保持 NOT_ESTIMABLE。"
                )
            st.caption(
                "相对 effort 只用于三套冻结方案排序，不是工时、金额、ROI 或成功承诺；"
                "未执行方案没有实测成功率。"
            )
            st.download_button(
                "下载整改可行性评估 JSON",
                canonical_json_bytes(outcome),
                file_name=f"{report.case_id}.outcome-assessment.json",
                mime="application/json",
                key=f"capa_outcome_download_{report.case_id}",
                width="stretch",
            )
    child_task_id = execution.child_task_id
    if st.button(
        f"查看 child Run · {child_task_id}",
        key=f"capa_child_{report.case_id}",
        width="stretch",
    ):
        st.session_state["selected_task_id"] = child_task_id
        _rerun()
    st.download_button(
        "下载 CAPA Case JSON",
        canonical_json_bytes(report),
        file_name=f"{report.case_id}.json",
        mime="application/json",
        key=f"capa_download_{report.case_id}",
        width="stretch",
    )


def _render_advanced_audit(user: Any, task: Any) -> None:
    trace_payload = SERVICE.read_trace(user.user_id, task.task_id)
    trace = RuntimeTrace.model_validate(trace_payload)
    canvas_html = build_runtime_canvas(trace, height=500)
    canvas_src = "data:text/html;base64," + base64.b64encode(
        canvas_html.encode("utf-8")
    ).decode("ascii")
    st.iframe(canvas_src, height=500)
    tabs = st.tabs(["运行事件", "任务依赖", "Agent 与能力", "审计产物"])
    with tabs[0]:
        st.dataframe(
            [
                {
                    "序号": event.sequence,
                    "阶段": event.stage.value,
                    "执行者": event.actor,
                    "状态": event.status.value,
                    "摘要": event.summary,
                }
                for event in trace.events
            ],
            hide_index=True,
            width="stretch",
        )
    with tabs[1]:
        st.dataframe(
            [
                {
                    "任务": item.title,
                    "执行者": item.actor,
                    "阶段": item.stage.value,
                    "状态": item.status.value,
                    "依赖": " · ".join(item.dependencies),
                }
                for item in trace.tasks
            ],
            hide_index=True,
            width="stretch",
        )
    with tabs[2]:
        snapshot = trace.agentteams
        if snapshot is not None:
            st.caption("本地协同契约映射；不是 hosted Matrix 连接回执。")
            st.dataframe(
                [
                    {
                        "身份": identity.display_name,
                        "类型": identity.role_type,
                        "职责": identity.purpose,
                        "能力": " · ".join(identity.capabilities),
                        "权限": " · ".join(identity.permission_scope),
                    }
                    for identity in snapshot.identities
                ],
                hide_index=True,
                width="stretch",
            )
            st.dataframe(
                [
                    {
                        "Skill": skill.name,
                        "版本": skill.version,
                        "用途": skill.purpose,
                        "失败模式": " · ".join(skill.failure_modes),
                        "安全边界": skill.safety_boundary,
                    }
                    for skill in snapshot.skills
                ],
                hide_index=True,
                width="stretch",
            )
    with tabs[3]:
        tool_fault = _load_task_payload(
            user, task, "tool_fault_intervention_receipt.json"
        )
        if tool_fault is not None:
            fault_summary = tool_fault.get("summary", {})
            st.markdown(
                "**工具运行时故障评测** · "
                f"`{tool_fault.get('status', 'UNKNOWN')}` · "
                f"检出 {fault_summary.get('detected_count', 0)}/"
                f"{fault_summary.get('intervention_count', 0)} · "
                f"Policy DEFER {fault_summary.get('policy_defer_count', 0)} 次"
            )
            st.caption(
                "覆盖 timeout、stale response、malformed payload、permission denied 与 poisoned contract；"
                "PASS_LOCAL 不代表自动恢复、真实网络 SLA 或生产韧性。"
            )
        else:
            st.caption(
                "该任务生成于运行时工具故障回执接入前；旧证据保持只读，不补写新结论。"
            )
        transport = _load_task_payload(user, task, "model_transport_receipt.json")
        injection = _load_task_payload(
            user, task, "prompt_injection_runtime_receipt.json"
        )
        backend_identity = _load_task_payload(
            user, task, "backend_identity_runtime_receipt.json"
        )
        safety_columns = st.columns(3)
        with safety_columns[0]:
            st.metric(
                "模型网络韧性",
                (transport or {}).get("status", "旧任务未生成"),
                help="本次运行的真实请求回执；固定超时/恢复评测另有独立 JSON。",
            )
        with safety_columns[1]:
            st.metric(
                "注入前置门",
                (injection or {}).get("status", "旧任务未生成"),
                help="命中攻击时阻断模型并确定性回退，不能替代 Frozen Policy Judge。",
            )
        with safety_columns[2]:
            st.metric(
                "外部后端身份",
                (backend_identity or {}).get("status", "旧任务未生成"),
                help="协议 fixture 与真实 LongCat/VGGT/OmniVGGT 连接分开标记。",
            )
        st.caption(
            "真实后端未探测成功时保持 REAL_BACKEND_NOT_CONNECTED；"
            "CONTRACT_CONNECTED_LOCAL_TEST 只表示本机协议夹具通过。"
        )
        artifacts = [
            "claim_scope_receipt.json",
            "runtime_contract_audit.json",
            "agent_eval_intervention_receipt.json",
            "tool_fault_intervention_receipt.json",
            "model_transport_receipt.json",
            "prompt_injection_runtime_receipt.json",
            "backend_identity_runtime_receipt.json",
            "skill_qualification_receipt.json",
            "tool_replay_receipt.json",
            "tool_ablation_receipt.json",
            "proof_index.json",
        ]
        for name in artifacts:
            try:
                artifact_bytes = SERVICE.read_evidence_zip_bytes(
                    user.user_id, task.task_id, name
                )
            except ArtifactUnavailableError:
                st.caption(f"{name}：当前任务未生成该产物。")
                continue
            st.download_button(
                f"下载 {name}",
                artifact_bytes,
                file_name=name,
                mime="application/json",
                key=f"download_{task.task_id}_{name}",
                width="stretch",
            )


def _render_annotation_roundtrip(user: Any, task: Any) -> None:
    st.markdown(
        """
<div class="vg-entry-grid">
  <article class="vg-entry"><small>01 · EXPORT</small><h3>生成整改任务包</h3><p>把 finding、工单、样本 ID、图像与标注版本哈希映射为 CVAT 或 FiftyOne 合同。</p><code>外部 ID 未绑定</code></article>
  <article class="vg-entry"><small>02 · RETURN</small><h3>接收修订标注</h3><p>逐条校验工单归属、样本键、源图哈希、前序版本、返回字节与掩码尺寸。</p><code>拒绝错配与伪回传</code></article>
  <article class="vg-entry"><small>03 · RECHECK</small><h3>同合同重新审核</h3><p>修订只写入独立副本；原始批次保持不变，再用冻结规则重新输出 Gate 结论。</p><code>same-contract</code></article>
</div>
""",
        unsafe_allow_html=True,
    )
    provider = st.selectbox(
        "整改系统",
        [AnnotationProvider.CVAT, AnnotationProvider.FIFTYONE],
        format_func=lambda item: (
            "CVAT" if item is AnnotationProvider.CVAT else "FiftyOne"
        ),
        key=f"annotation_provider_{task.task_id}",
    )
    state_key = f"annotation_export_{task.task_id}_{provider.value}"
    if st.button(
        "生成整改任务包",
        type="primary",
        key=f"annotation_export_button_{task.task_id}_{provider.value}",
        width="stretch",
    ):
        try:
            record = SERVICE.create_annotation_export(
                user.user_id, task.task_id, provider
            )
        except (ValidationError, ProductServiceError, OSError, ValueError) as error:
            st.error(f"整改任务包未生成：{str(error)[:240]}")
        else:
            st.session_state[state_key] = record.model_dump(mode="json")
            st.success("整改任务包已按当前 Gate 结果冻结；外部服务尚未自动连接。")

    record_payload = st.session_state.get(state_key)
    if record_payload:
        record = AnnotationExportRecord.model_validate(record_payload)
        eligible = sum(
            item.eligible_for_annotation_return for item in record.bundle.tasks
        )
        c1, c2, c3 = st.columns(3)
        c1.metric("整改工单", len(record.bundle.tasks))
        c2.metric("关联样本", len(record.bundle.samples))
        c3.metric("可回传标注工单", eligible)
        st.markdown(
            '<div class="vg-boundary"><b>连接状态：</b>适配合同已生成，CVAT/FiftyOne 外部任务 ID 尚未绑定；这不是外部服务连接成功的回执。</div>',
            unsafe_allow_html=True,
        )
        st.download_button(
            "下载整改任务包 JSON",
            canonical_json_bytes(record),
            file_name=f"{task.task_id}-{provider.value}-annotation-export.json",
            mime="application/json",
            key=f"annotation_export_download_{task.task_id}_{provider.value}",
            width="stretch",
        )
        template = {
            "schema_version": "visiondata-gate.annotation-import.v1",
            "export_id": record.bundle.export_id,
            "provider": provider.value,
            "revisions": [
                {
                    "work_order_id": "copy from export",
                    "internal_sample_id": "copy from export",
                    "external_sample_key": "copy from export",
                    "external_task_id": None,
                    "source_image_sha256": "copy from export",
                    "prior_annotation_sha256": None,
                    "annotation_version": "review-v2",
                    "annotation_content_base64": "base64 encoded PNG mask",
                }
            ],
        }
        with st.expander("查看回传 JSON 合同"):
            st.code(
                json.dumps(template, ensure_ascii=False, indent=2),
                language="json",
            )
        uploaded = st.file_uploader(
            "上传修订回传 JSON",
            type=["json"],
            key=f"annotation_import_upload_{task.task_id}_{provider.value}",
            help="当前工作台仅接收严格 JSON；不会接受客户端本地文件路径。",
        )
        if uploaded is not None and st.button(
            "校验回传并同合同复验",
            key=f"annotation_import_button_{task.task_id}_{provider.value}",
            width="stretch",
        ):
            try:
                package = AnnotationImportPackage.model_validate_json(
                    uploaded.getvalue()
                )
                receipt = SERVICE.import_annotation_revisions(
                    user.user_id, task.task_id, package
                )
            except (ValidationError, ProductServiceError, OSError, ValueError) as error:
                st.error(f"回传未通过：{str(error)[:260]}")
            else:
                st.session_state[f"annotation_receipt_{task.task_id}"] = (
                    receipt.model_dump(mode="json")
                )
                st.success(
                    f"已接受 {receipt.accepted_revision_count}/{receipt.submitted_revision_count} 条修订；"
                    + (
                        f"同合同复验结论 {receipt.recheck_decision}。"
                        if receipt.same_contract_recheck_performed
                        else "没有合格修订，因此未声称完成复验。"
                    )
                )

    try:
        receipts = SERVICE.list_annotation_roundtrips(user.user_id, task.task_id)
    except (ProductServiceError, OSError, ValueError) as error:
        st.error(f"往返回执未通过完整性校验：{str(error)[:240]}")
        receipts = []
    if receipts:
        st.markdown(
            '<div class="vg-head"><h2>往返回执</h2><span>本地合同验证与外部连接分开记录</span></div>',
            unsafe_allow_html=True,
        )
        st.dataframe(
            [
                {
                    "回执": item.receipt_id,
                    "系统": item.provider.value,
                    "外部已连接": "是" if item.external_connected else "否",
                    "回传保真度": item.roundtrip_fidelity,
                    "闭环率": item.remediation_closure_rate,
                    "同合同复验": item.recheck_decision or "未执行",
                    "原批次不变": "是" if item.original_input_unchanged else "否",
                }
                for item in receipts
            ],
            hide_index=True,
            width="stretch",
        )


def _render_task_lineage(user: Any, task: Any) -> None:
    """Expose immutable remediation lineage without replacing the parent result."""

    try:
        report = SERVICE.task_lineage(user.user_id, task.task_id)
    except (ProductServiceError, ProductStoreError, OSError, ValueError) as error:
        st.error(f"复验运行链不可用：{str(error)[:240]}")
        return
    st.markdown(
        '<div class="vg-head"><h2>整改与复验运行链</h2>'
        "<span>原裁决不可变 · 新版本新 Run · 同一检查合同</span></div>",
        unsafe_allow_html=True,
    )
    metrics = st.columns(3)
    metrics[0].metric("运行代数", report.node_count)
    metrics[1].metric("复验分支", report.edge_count)
    metrics[2].metric(
        "当前记录", "最新" if report.focus_task_id == report.latest_task_id else "历史"
    )
    st.dataframe(
        [
            {
                "代": item.depth,
                "运行": item.task_id,
                "关系": "原始审核" if item.relation == "initial" else "整改后复验",
                "父运行": item.parent_task_id or "—",
                "状态": item.execution_status.value,
                "裁决": item.final_decision or "待运行",
                "证据 SHA": (item.evidence_sha256 or "")[:12] or "—",
                "当前查看": "是" if item.is_focus else "否",
            }
            for item in report.nodes
        ],
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "每个复验 Run 继承相同规则包、工具白名单和固定种子；父 Run 的请求与证据 SHA "
        "写入只追加边，整改后的输入以新的 source_id 和新证据包保存。"
    )
    with st.expander("查看运行链哈希与下载审计报告"):
        st.code(
            f"Contract SHA-256  {report.contract_sha256}\n"
            f"Lineage SHA-256   {report.report_sha256}",
            language=None,
        )
        st.caption(report.claim_boundary)
        st.download_button(
            "下载复验运行链 JSON",
            canonical_json_bytes(report),
            file_name=f"{task.task_id}-lineage.json",
            mime="application/json",
            key=f"lineage_download_{task.task_id}",
            width="stretch",
        )

    if task.execution_status is not TaskExecutionStatus.COMPLETED:
        return
    with st.expander("基于本次裁决创建同合同复验 Run"):
        st.info(
            "系统不会覆盖本次裁决。新 Run 必须再次通过 Preflight 和人工计划批准；"
            "如果整改改变了目录内容，请先在“数据源”中登记新的只读版本。"
        )
        source_id = None
        can_create = True
        if task.source_kind is DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY:
            sources = [
                item
                for item in SERVICE.list_local_source_authorizations(
                    user.user_id, task.workspace_id
                )
                if item.status == "active"
            ]
            if sources:
                source_ids = [item.source_id for item in sources]
                default_source = (
                    task.source_id if task.source_id in source_ids else source_ids[0]
                )
                source_id = st.selectbox(
                    "复验数据版本",
                    source_ids,
                    index=source_ids.index(default_source),
                    format_func=lambda value: next(
                        (
                            f"{item.display_name} · "
                            f"{item.data_profile.get('source_image_count', 0)} 张图像 · "
                            f"{str(item.data_profile.get('profile_sha256', ''))[:10]}"
                        )
                        for item in sources
                        if item.source_id == value
                    ),
                    key=f"reverification_source_{task.task_id}",
                )
            else:
                st.warning("没有可用于复验的有效只读数据版本。")
                can_create = False
        note = st.text_area(
            "本次整改/复验说明",
            value="已按责任队列完成整改，申请在相同规则、工具和固定种子下重新审核。",
            height=88,
            key=f"reverification_note_{task.task_id}",
        )
        create = st.button(
            "创建复验 Run，等待人工计划批准",
            type="primary",
            width="stretch",
            disabled=not can_create,
            key=f"create_reverification_{task.task_id}",
        )
        if create:
            try:
                child = SERVICE.create_reverification_task(
                    user.user_id,
                    task.task_id,
                    CreateReverificationRequest(note=note, source_id=source_id),
                )
            except (
                ValidationError,
                ProductServiceError,
                ProductStoreError,
                OSError,
                ValueError,
            ) as error:
                st.error(f"复验 Run 未创建：{str(error)[:240]}")
            else:
                st.session_state["selected_task_id"] = child.task_id
                st.success(f"复验 Run 已创建并等待计划审核：{child.task_id}")
                _rerun()


def _render_task_detail(user: Any, task: Any) -> None:
    st.markdown(
        f'<div class="vg-head"><h2>任务详情</h2><span>{_e(task.task_id)}</span></div>',
        unsafe_allow_html=True,
    )
    st.markdown(_timeline(task.execution_status), unsafe_allow_html=True)
    st.caption(f"目标：{task.goal}")
    _render_task_lineage(user, task)
    if _render_task_governance(user, task):
        return
    if task.execution_status in {
        TaskExecutionStatus.PLANNED,
        TaskExecutionStatus.RUNNING,
        TaskExecutionStatus.VERIFYING,
    }:
        st.info("任务正在执行。点击侧栏“刷新任务状态”获取最新进度。")
        events = SERVICE.list_events(user.user_id, task.task_id)
        if events:
            st.dataframe(
                [
                    {"阶段": item.stage, "状态": item.status, "摘要": item.summary}
                    for item in events[-12:]
                ],
                hide_index=True,
                width="stretch",
            )
        return
    if task.execution_status is TaskExecutionStatus.FAILED:
        st.error(
            f"本轮运行失败：{task.error_code or 'unknown_error'}。未恢复历史结果作为当前结果。"
        )
        return
    is_local_source = task.source_kind is DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY
    initial = _load_task_payload(user, task, "initial/gate_result.json") or {}
    if is_local_source:
        final = _load_task_payload(user, task, "final/gate_result.json") or {}
    else:
        final = _load_task_payload(user, task, "repaired/gate_result.json") or {}
    primary_result = final if is_local_source else initial
    decision = task.final_decision or "UNKNOWN"
    decision_reason = DECISION_EXPLANATIONS.get(
        decision, "同规则复验已完成，详情见审核凭证。"
    )
    tool_labels = "、".join(_tool_label(item) for item in task.allowed_tools)
    final_metric_label = "最终问题" if is_local_source else "复验后问题"
    source_summary = _source_label(task.source_kind)
    if is_local_source:
        plan = _load_task_payload(user, task, "dynamic_leader_plan.json") or {}
        tool_labels = (
            f"{plan.get('static_task_count', 5)} 个静态工具 + "
            f"{plan.get('dynamic_task_count', 0)} 个动态 Worker"
        )
    st.markdown(
        f"""
<section class="vg-detail-hero">
  <div class="vg-decision {_e(decision.lower())}"><small>最终审核结论</small><b>{_e(decision)}</b><p>{_e(decision_reason)}</p></div>
    <div class="vg-detail-metrics">
  <div class="vg-detail-metric"><small>首轮问题</small><b>{len(initial.get("findings", []))}</b></div>
  <div class="vg-detail-metric"><small>整改任务</small><b>{len(initial.get("work_orders", []))}</b></div>
  <div class="vg-detail-metric"><small>{_e(final_metric_label)}</small><b>{len(final.get("findings", []))}</b></div>
  <div class="vg-detail-config"><b>冻结配置</b> · {_e(source_summary)} · {_e(_scenario_label(task.scenario_profile))} · 固定种子 {_e(task.seed)}<br><span>· 工具编排：{_e(tool_labels)}</span></div>
  </div>
</section>
""",
        unsafe_allow_html=True,
    )
    st.caption(
        "门禁结论与系统运行状态分开保存；DEFER 是正确完成的暂缓决定，不等于系统异常。"
    )
    if is_local_source:
        tabs = st.tabs(
            [
                "证据链",
                "动态补证",
                "发现的问题",
                "处置底账",
                "方案与复验",
                "审核凭证",
            ]
        )
        findings_tab = tabs[2]
        orders_tab = tabs[3]
        industrial_tab = tabs[4]
        receipt_tab = tabs[5]
    else:
        tabs = st.tabs(["证据链", "发现的问题", "整改任务", "整改往返", "审核凭证"])
        findings_tab = tabs[1]
        orders_tab = tabs[2]
        receipt_tab = tabs[4]
    with tabs[0]:
        _render_evidence_chain(user, task)
    if is_local_source:
        with tabs[1]:
            _render_dynamic_followups(user, task)
        with industrial_tab:
            _render_industrial_delivery(user, task)
            _render_capa_control(user, task)
    with findings_tab:
        findings = primary_result.get("findings", [])
        if findings:
            st.dataframe(
                [
                    {
                        "严重度": item.get("severity", ""),
                        "问题": item.get("summary", ""),
                        "样本": " · ".join(item.get("sample_ids", [])),
                        "证据状态": item.get("evidence_status", ""),
                        "检查能力": _tool_label(item.get("tool", "")),
                    }
                    for item in findings
                ],
                hide_index=True,
                width="stretch",
            )
        else:
            st.success("未发现阻断问题。")
    with orders_tab:
        orders = primary_result.get("work_orders", [])
        st.dataframe(
            [
                {
                    "优先级": item.get("priority", ""),
                    "动作": item.get("action", ""),
                    "状态": item.get("status", ""),
                    "样本": " · ".join(item.get("sample_ids", [])),
                    "原因": " · ".join(item.get("reason_codes", [])),
                }
                for item in orders
            ],
            hide_index=True,
            width="stretch",
        )
    if not is_local_source:
        with tabs[3]:
            _render_annotation_roundtrip(user, task)
    with receipt_tab:
        evidence = SERVICE.evidence_path(user.user_id, task.task_id)
        trace = SERVICE.trace_path(user.user_id, task.task_id)
        c1, c2 = st.columns(2)
        c1.download_button(
            "下载完整审核凭证 ZIP",
            evidence.read_bytes(),
            file_name=f"{task.task_id}-evidence.zip",
            mime="application/zip",
            key=f"evidence_{task.task_id}",
            width="stretch",
        )
        c2.download_button(
            "下载运行详情 JSON",
            trace.read_bytes(),
            file_name=f"{task.task_id}-runtime-trace.json",
            mime="application/json",
            key=f"trace_{task.task_id}",
            width="stretch",
        )
        st.code(f"Evidence SHA-256  {task.evidence_sha256}", language=None)
        try:
            scorecard_receipts = SERVICE.list_annotation_roundtrips(
                user.user_id, task.task_id
            )
        except (ProductServiceError, OSError, ValueError) as error:
            st.error(f"整改回执未通过完整性校验：{str(error)[:240]}")
            scorecard_receipts = []
        selected_receipt_id = None
        if len(scorecard_receipts) == 1:
            selected_receipt_id = scorecard_receipts[0].receipt_id
        elif len(scorecard_receipts) > 1:
            selected_receipt_id = st.selectbox(
                "验收指标绑定的整改回执",
                [item.receipt_id for item in scorecard_receipts],
                key=f"scorecard_receipt_{task.task_id}",
            )
        try:
            scorecard = SERVICE.acceptance_scorecard(
                user.user_id,
                task.task_id,
                roundtrip_receipt_id=selected_receipt_id,
            )
        except (ProductServiceError, OSError, ValueError) as error:
            st.error(f"验收指标未生成：{str(error)[:240]}")
            scorecard = None
        if scorecard is not None:
            st.markdown(
                '<div class="vg-head"><h2>企业验收指标</h2><span>缺失指标不会被填成 0</span></div>',
                unsafe_allow_html=True,
            )
            st.dataframe(
                [
                    {
                        "指标": item.label,
                        "结果": item.value,
                        "单位": item.unit or "—",
                        "目标": item.target,
                        "状态": item.status,
                        "证据": item.source_ref,
                    }
                    for item in scorecard.metrics
                ],
                hide_index=True,
                width="stretch",
            )
            st.download_button(
                "下载企业验收指标 JSON",
                canonical_json_bytes(scorecard),
                file_name=f"{task.task_id}-acceptance-scorecard.json",
                mime="application/json",
                key=f"acceptance_scorecard_{task.task_id}",
                width="stretch",
            )
    st.markdown(
        '<div class="vg-head"><h2>高级审计</h2><span>按需加载 Runtime Canvas 与协议回执</span></div>',
        unsafe_allow_html=True,
    )
    show_advanced_audit = st.toggle(
        "加载 Runtime Canvas、任务 DAG 与协议回执",
        value=False,
        key=f"advanced_audit_{task.task_id}",
        help="高级审计会解析完整 trace 与证据包；日常查看结论时无需加载。",
    )
    if show_advanced_audit:
        _render_advanced_audit(user, task)


def _render_industrial_incidents(user: Any, workspace: Any) -> None:
    st.title("异常处置")
    st.caption(
        "面向质量负责人：把换型后的 NG 异常变成可补证、可暂停、可整改、可独立复验的案件。"
    )
    st.markdown(
        """
<div class="vg-entry-grid">
  <article class="vg-entry"><small>01 · TRIGGER</small><h3>换型后异常</h3><p>NG 率突升、新缺陷簇或视觉方案变化，触发一个有版本的质量案件。</p><code>一个事件 · 一个责任入口</code></article>
  <article class="vg-entry"><small>02 · INVESTIGATE</small><h3>动态补证</h3><p>Agent 按证据缺口增派信号、追溯、工艺、视觉方案或反证审计角色。</p><code>不是固定 DAG</code></article>
  <article class="vg-entry"><small>03 · INTERRUPT</small><h3>人工中断</h3><p>证据不足、方案选择与复验动作都必须停在具名质量负责人面前。</p><code>Agent 无生产权限</code></article>
  <article class="vg-entry"><small>04 · REVERIFY</small><h3>派生版本复验</h3><p>批准后的整改沿用既有 CAPA 与 child Run，旧案件和旧证据不被覆盖。</p><code>父子 Run 可追溯</code></article>
</div>
""",
        unsafe_allow_html=True,
    )

    tasks = [
        task
        for task in SERVICE.list_tasks(
            user.user_id, workspace_id=workspace.workspace_id, limit=200
        )
        if task.execution_status is TaskExecutionStatus.COMPLETED
    ]
    if not tasks:
        st.info("请先完成一条 Gate 任务；异常案件只接受已经冻结证据的任务。")
        return

    task_ids = [task.task_id for task in tasks]
    incident_task_state_key = "incident_task_id"
    if st.session_state.get(incident_task_state_key) not in task_ids:
        for candidate in tasks:
            try:
                if SERVICE.list_industrial_incident_cases(
                    user.user_id, candidate.task_id
                ):
                    st.session_state[incident_task_state_key] = candidate.task_id
                    break
            except (ProductServiceError, ProductStoreError, OSError, ValueError):
                continue
    selected_task_id = st.selectbox(
        "选择已完成的视觉 Gate",
        task_ids,
        format_func=lambda task_id: next(
            (
                f"{item.goal[:46]} · {_source_label(item.source_kind)} · "
                f"{item.final_decision or 'UNKNOWN'}"
            )
            for item in tasks
            if item.task_id == task_id
        ),
        key=incident_task_state_key,
    )
    task = next(item for item in tasks if item.task_id == selected_task_id)
    try:
        cases = SERVICE.list_industrial_incident_cases(user.user_id, task.task_id)
    except (ProductServiceError, ProductStoreError, OSError, ValueError) as error:
        st.error(f"案件列表未能通过完整性校验：{str(error)[:240]}")
        return

    if not cases:
        source_is_local = task.source_kind is DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY
        st.markdown(
            '<div class="vg-head"><h2>建立第一条案件</h2><span>不会控制设备，也不会自动放行</span></div>',
            unsafe_allow_html=True,
        )
        if source_is_local:
            st.info(
                "当前 Gate 来自本地授权工业数据；下方快捷入口只为过程信号与视觉方案生成明确标注的 Fixture，真实 Gate 证据仍按原 SHA-256 绑定。"
            )
        else:
            st.warning(
                "当前 Gate 使用合成数据，创建的案件只能验证产品闭环，不能写成工厂现场结果。"
            )
        create_col, import_col = st.columns(2)
        with create_col:
            st.markdown("#### 快捷闭环演练")
            st.caption("内置一个换型后 NG 漂移、工艺窗口变化和方案漂移的显式 Fixture。")
            if st.button(
                "创建 Fixture 异常案件",
                key=f"create_incident_fixture_{task.task_id}",
                type="primary",
                width="stretch",
            ):
                try:
                    case = SERVICE.create_industrial_incident_case(
                        user.user_id,
                        task.task_id,
                        build_fixture_industrial_incident_request(
                            triggered_at=datetime.now(UTC)
                        ).model_copy(update={"max_dynamic_workers": 12}),
                    )
                except (
                    ProductServiceError,
                    ProductStoreError,
                    OSError,
                    ValueError,
                ) as error:
                    st.error(f"案件创建失败：{str(error)[:240]}")
                else:
                    st.session_state[f"_pending_incident_case_id_{task.task_id}"] = (
                        case.case_id
                    )
                    _rerun()
        with import_col:
            st.markdown("#### 导入只读证据包")
            uploaded = st.file_uploader(
                "工业异常请求 JSON",
                type=["json"],
                key=f"incident_import_{task.task_id}",
                help="仅接受脱敏的离线 OPC UA 快照、视觉方案 Manifest 与离线运行回执。",
            )
            if st.button(
                "校验并建立案件",
                key=f"create_incident_import_{task.task_id}",
                disabled=uploaded is None,
                width="stretch",
            ):
                try:
                    payload = parse_industrial_incident_request_json(
                        uploaded.getvalue() if uploaded is not None else b""
                    )
                    case = SERVICE.create_industrial_incident_case(
                        user.user_id, task.task_id, payload
                    )
                except (
                    ValidationError,
                    ProductServiceError,
                    ProductStoreError,
                    OSError,
                    ValueError,
                ) as error:
                    st.error(f"证据包未通过校验：{str(error)[:240]}")
                else:
                    st.session_state[f"_pending_incident_case_id_{task.task_id}"] = (
                        case.case_id
                    )
                    _rerun()
        return

    case_ids = [item.case_id for item in cases]
    case_state_key = f"incident_case_id_{task.task_id}"
    pending_case_state_key = f"_pending_incident_case_id_{task.task_id}"
    pending_case_id = st.session_state.pop(pending_case_state_key, None)
    if pending_case_id in case_ids:
        st.session_state[case_state_key] = pending_case_id
    selected_case_id = st.session_state.get(case_state_key)
    if selected_case_id not in case_ids:
        selected_case_id = case_ids[-1]
    selected_case_id = st.selectbox(
        "案件版本",
        case_ids,
        index=case_ids.index(selected_case_id),
        format_func=lambda case_id: next(
            (
                f"v{item.case_version} · "
                f"{INCIDENT_STATUS_LABELS.get(item.status.value, item.status.value)} · "
                f"{item.request.trigger.triggered_at:%m-%d %H:%M}"
            )
            for item in cases
            if item.case_id == case_id
        ),
        key=case_state_key,
    )
    case = next(item for item in cases if item.case_id == selected_case_id)
    try:
        decisions = SERVICE.list_industrial_incident_decisions(
            user.user_id, task.task_id, case.case_id
        )
        phase_events = SERVICE.list_industrial_incident_phase_events(
            user.user_id, task.task_id, case.case_id
        )
    except (ProductServiceError, ProductStoreError, OSError, ValueError) as error:
        st.error(f"案件回执或执行事件未通过完整性校验：{str(error)[:240]}")
        return

    status_label = INCIDENT_STATUS_LABELS.get(case.status.value, case.status.value)
    recommendation_label = INCIDENT_RECOMMENDATION_LABELS.get(
        case.recommendation.value, case.recommendation.value
    )
    active_hypothesis_count = sum(
        item.status.value != "REJECTED" for item in case.hypotheses
    )
    metrics = st.columns([1.35, 0.75, 0.75, 0.9, 1.0])
    metrics[0].metric("当前状态", status_label)
    metrics[1].metric("案件版本", f"v{case.case_version}")
    metrics[2].metric("证据引用", len(case.evidence_refs))
    metrics[3].metric("竞争性解释", active_hypothesis_count)
    metrics[4].metric("本轮动态 Worker", case.dynamic_branch_count)

    canvas_html = build_incident_canvas(case, height=500)
    canvas_src = "data:text/html;base64," + base64.b64encode(
        canvas_html.encode("utf-8")
    ).decode("ascii")
    st.iframe(canvas_src, height=500)
    if case.opcua_connection_status == "OPC_UA_FIXTURE_REPLAY_ONLY":
        st.warning(
            "过程信号与视觉方案是 Fixture Replay，只验证 Agent 闭环；未连接真实 OPC UA 端点或 VisionMaster SDK。"
        )
    else:
        st.info(
            "过程证据来自脱敏离线只读导出；系统未连接真实 OPC UA 端点，也没有设备写权限。"
        )
    if phase_events:
        worker_event_count = sum(
            item.invocation_id.startswith("worker_invocation_") for item in phase_events
        )
        st.caption(
            f"执行链已验签：{len(phase_events)} 条只增事件 · "
            f"{worker_event_count} 次实际 Worker 调用 · "
            f"链尾 {phase_events[-1].event_sha256[:12]}…"
        )
        with st.expander("查看 Agent 执行证据链"):
            st.dataframe(
                [
                    {
                        "序号": item.sequence,
                        "阶段": item.phase,
                        "执行者": item.actor,
                        "状态": item.status,
                        "输入 SHA": item.input_sha256[:12] + "…",
                        "输出 SHA": item.output_sha256[:12] + "…",
                        "前序事件": (
                            item.prev_event_sha256[:12] + "…"
                            if item.prev_event_sha256
                            else "链头"
                        ),
                    }
                    for item in phase_events
                ],
                hide_index=True,
                width="stretch",
            )

    context_col, decision_col, action_col = st.columns([0.9, 1.15, 0.95])
    with context_col:
        st.markdown("#### 异常上下文")
        trigger = case.request.trigger
        rate_change = "—"
        if (
            trigger.baseline_ng_rate is not None
            and trigger.observed_ng_rate is not None
        ):
            rate_change = (
                f"{trigger.baseline_ng_rate:.1%} → {trigger.observed_ng_rate:.1%}"
            )
        st.markdown(
            f"""
- **触发事件**：{_e(trigger.trigger_kind.value)}
- **NG 变化**：{_e(rate_change)}
- **父 Gate**：{_e(case.gate_context.gate_final_decision)}
- **聚合风险流**：{case.gate_context.risk_cluster_count}
- **待处置原子记录**：{case.gate_context.open_work_order_count}
- **新循环模型调用**：{case.external_model_call_count}
"""
        )
        st.caption(trigger.operator_message)
    with decision_col:
        st.markdown("#### Agent 当前交付")
        st.markdown(f"**建议：{_e(recommendation_label)}**")
        st.write(case.recommendation_reason)
        for fact in case.decision_summary.observed_facts:
            st.markdown(f"- {fact}")
        with st.expander("仍未排除的解释"):
            for hypothesis in case.hypotheses:
                if hypothesis.status.value == "REJECTED":
                    continue
                st.markdown(f"**{hypothesis.status.value}** · {hypothesis.statement}")
                st.caption(hypothesis.next_discriminating_test)
    with action_col:
        st.markdown("#### 人工决定已记录" if decisions else "#### 等待人工决定")
        if decisions:
            st.success(
                f"唯一活动决定：{decisions[-1].decision.value}。"
                "该回执必须被下一案件版本显式消费。"
            )
        for question in case.operator_questions[:4]:
            marker = "已由决定回执承接" if decisions else "待回答"
            st.markdown(f"- **{marker}** · {question.prompt}")
        decision_options = [
            IncidentHumanDecision.CONTINUE_HOLD,
            IncidentHumanDecision.ESCALATE_INVESTIGATION,
            IncidentHumanDecision.REQUEST_REVERIFICATION,
            IncidentHumanDecision.REJECT_RECOMMENDATION,
        ]
        if case.linked_remediation_plan_ids:
            decision_options.insert(2, IncidentHumanDecision.SELECT_REMEDIATION_PLAN)
        decision_labels = {
            IncidentHumanDecision.CONTINUE_HOLD: "继续保持 HOLD",
            IncidentHumanDecision.ESCALATE_INVESTIGATION: "转联合调查",
            IncidentHumanDecision.SELECT_REMEDIATION_PLAN: "选择整改方案",
            IncidentHumanDecision.REQUEST_REVERIFICATION: "请求独立复验",
            IncidentHumanDecision.REJECT_RECOMMENDATION: "驳回当前建议",
        }
        with st.form(f"incident_decision_{case.case_id}"):
            chosen_decision = st.selectbox(
                "人工动作",
                decision_options,
                format_func=lambda value: decision_labels[value],
            )
            chosen_plan = None
            if case.linked_remediation_plan_ids:
                chosen_plan = st.selectbox(
                    "候选整改方案",
                    case.linked_remediation_plan_ids,
                    help="只有选择整改方案时才会创建 CAPA；仍不会自动批准或执行。",
                )
            decision_note = st.text_area(
                "复核记录",
                value="",
                placeholder="写明你核对了哪些证据、保留了哪些风险，以及下一位责任人。",
            )
            reviewed = st.checkbox("我已核对当前证据和权限边界", value=False)
            submitted = st.form_submit_button(
                "已冻结决定" if decisions else "记录具名决定",
                type="primary",
                width="stretch",
                disabled=bool(decisions),
            )
        if submitted:
            try:
                SERVICE.record_industrial_incident_decision(
                    user.user_id,
                    task.task_id,
                    case.case_id,
                    IndustrialIncidentDecisionRequest(
                        bound_case_sha256=case.case_sha256,
                        decision=chosen_decision,
                        note=decision_note,
                        selected_remediation_plan_id=(
                            chosen_plan
                            if chosen_decision
                            is IncidentHumanDecision.SELECT_REMEDIATION_PLAN
                            else None
                        ),
                        operator_attests_reviewed_evidence=reviewed,
                    ),
                )
            except (
                ValidationError,
                ProductServiceError,
                ProductStoreError,
                OSError,
                ValueError,
            ) as error:
                st.error(f"人工决定未记录：{str(error)[:240]}")
            else:
                _rerun()

    if decisions:
        st.markdown(
            '<div class="vg-head"><h2>人工决定时间线</h2><span>每条回执绑定案件 SHA-256</span></div>',
            unsafe_allow_html=True,
        )
        st.dataframe(
            [
                {
                    "时间": item.decided_at.strftime("%m-%d %H:%M:%S"),
                    "决定": item.decision.value,
                    "说明": item.note,
                    "CAPA": item.linked_capa_case_id or "—",
                    "生产放行": "不允许",
                }
                for item in decisions
            ],
            hide_index=True,
            width="stretch",
        )

        latest_decision = decisions[-1]
        if latest_decision.linked_capa_case_id is not None:
            _render_capa_control(
                user,
                task,
                locked_case_id=latest_decision.linked_capa_case_id,
            )

    st.markdown(
        '<div class="vg-head"><h2>补证后续跑</h2><span>创建新案件版本，不覆盖当前证据</span></div>',
        unsafe_allow_html=True,
    )
    if not case.loop_control.can_resume:
        st.info("当前案件已达到冻结循环上限；请转人工调查或进入既有 CAPA/复验链。")
    elif not decisions:
        st.info("Agent 已暂停；先记录一条具名人工决定，才能提交新证据续跑。")
    elif case.opcua_connection_status == "OPC_UA_FIXTURE_REPLAY_ONLY":
        st.caption(
            "演练入口会生成一份带新时间戳的 Fixture 证据版本；它用于验证暂停/恢复和 lineage，不是现场补证。"
        )
        if st.button(
            "生成新 Fixture 证据并续跑",
            key=f"resume_incident_fixture_{case.case_id}",
            width="stretch",
        ):
            try:
                refreshed = build_fixture_industrial_incident_request(
                    triggered_at=datetime.now(UTC)
                ).model_copy(
                    update={
                        "max_agent_iterations": case.request.max_agent_iterations,
                        "max_dynamic_workers": case.request.max_dynamic_workers,
                        "supersedes_case_id": case.case_id,
                        "expected_parent_case_sha256": case.case_sha256,
                        "authorizing_decision_id": decisions[-1].decision_id,
                    }
                )
                child = SERVICE.resume_industrial_incident_case(
                    user.user_id, task.task_id, case.case_id, refreshed
                )
            except (
                ProductServiceError,
                ProductStoreError,
                OSError,
                ValueError,
            ) as error:
                st.error(f"案件续跑失败：{str(error)[:240]}")
            else:
                st.session_state[pending_case_state_key] = child.case_id
                _rerun()
    else:
        resumed_upload = st.file_uploader(
            "上传新的脱敏工业异常请求 JSON",
            type=["json"],
            key=f"resume_incident_import_{case.case_id}",
        )
        if st.button(
            "校验新证据并续跑",
            key=f"resume_incident_import_button_{case.case_id}",
            disabled=resumed_upload is None,
            width="stretch",
        ):
            try:
                refreshed = parse_industrial_incident_request_json(
                    resumed_upload.getvalue() if resumed_upload is not None else b""
                ).model_copy(
                    update={
                        "supersedes_case_id": case.case_id,
                        "expected_parent_case_sha256": case.case_sha256,
                        "authorizing_decision_id": decisions[-1].decision_id,
                    }
                )
                child = SERVICE.resume_industrial_incident_case(
                    user.user_id, task.task_id, case.case_id, refreshed
                )
            except (
                ValidationError,
                ProductServiceError,
                ProductStoreError,
                OSError,
                ValueError,
            ) as error:
                st.error(f"新证据未通过校验：{str(error)[:240]}")
            else:
                st.session_state[pending_case_state_key] = child.case_id
                _rerun()

    with st.expander("查看安全边界与可下载案件"):
        for boundary in case.decision_summary.prohibited_conclusions:
            st.markdown(f"- {boundary}")
        st.download_button(
            "下载当前案件 JSON",
            canonical_json_bytes(case),
            file_name=f"{case.case_id}-v{case.case_version}.json",
            mime="application/json",
            key=f"download_incident_{case.case_id}",
            width="stretch",
        )


def _render_runs(user: Any, workspace: Any) -> None:
    st.title("审核记录")
    st.caption("每条记录都保留创建时的目标、规则包、工具权限和证据引用。")
    tasks = SERVICE.list_tasks(
        user.user_id, workspace_id=workspace.workspace_id, limit=200
    )
    if not tasks:
        st.info("当前工作区还没有运行记录。")
        return
    task_ids = [task.task_id for task in tasks]
    selected = st.session_state.get("selected_task_id")
    if selected not in task_ids:
        selected = task_ids[0]
    selected_id = st.selectbox(
        "选择任务",
        task_ids,
        index=task_ids.index(selected),
        format_func=lambda task_id: next(
            f"{item.goal[:48]} · {item.execution_status.value}"
            for item in tasks
            if item.task_id == task_id
        ),
        key="selected_task_id",
    )
    task = next(item for item in tasks if item.task_id == selected_id)
    _render_task_detail(user, task)


def _render_skills() -> None:
    st.title("能力目录")
    st.caption("可复用能力带有输入范围、权限和失败语义；缺失必需能力时系统安全暂缓。")
    labels = {
        "image_quality": ("图像质量", "解码、清晰度、曝光与尺寸合同"),
        "duplicate_leakage": ("重复与泄漏", "精确重复、近似重复和数据集泄漏"),
        "annotation_integrity": ("标注完整性", "路径、尺寸、掩码与标签一致性"),
        "coverage_matrix": ("覆盖完整性", "场景、视角和条件组合覆盖"),
        "governance_audit": ("治理审计", "合同、清单和场景规则的一致性"),
    }
    catalog = tool_catalog(include_optional=True)
    columns = st.columns(2)
    for index, item in enumerate(catalog):
        title, body = labels[str(item["name"])]
        with columns[index % 2]:
            st.markdown(
                f'<div class="vg-card"><small>v1 · {_e(item["permission"])} · {_e(item["scope"])}</small><h3>{_e(title)}</h3><p>{_e(body)}。工具输出 finding code 与可复算证据，不能直接覆盖审核决策。</p></div>',
                unsafe_allow_html=True,
            )
    st.markdown(
        '<div class="vg-head"><h2>接入契约</h2><span>第三方能力扩展思路</span></div>',
        unsafe_allow_html=True,
    )
    st.code(
        """skill_id: image_quality
version: 1.0.0
input: batch_manifest + frozen_contract
output: findings + tool_trace
permission: dataset:read
on_failure: DEFER
decision_authority: none""",
        language="yaml",
    )


def _render_api(user: Any, project: Any | None) -> None:
    st.title("API 接入")
    st.caption("把审核任务接入企业 Agent、SaaS 系统或内部流水线。")
    if project is None:
        st.info("创建项目后会生成可直接复制的调用示例。")
        return
    st.markdown(
        """
<div class="vg-entry-grid">
  <article class="vg-entry"><small>01 · SUBMIT</small><h3>提交任务</h3><p>企业 Agent、SaaS 或流水线提交目标、项目和幂等键，立即获得任务 ID 与 Location。</p><code>202 Accepted</code></article>
  <article class="vg-entry"><small>02 · OBSERVE</small><h3>跟踪生命周期</h3><p>按任务 ID 查询状态与 append-only 事件，不把运行中或证据不足误写成成功。</p><code>GET /tasks · /events</code></article>
  <article class="vg-entry"><small>03 · REMEDIATE</small><h3>整改与回传</h3><p>导出 CVAT/FiftyOne 任务合同，拉回修订标注并校验样本、版本和哈希后同规则复验。</p><code>/annotation-exports · /imports</code></article>
  <article class="vg-entry"><small>04 · DELIVER</small><h3>交付可验证结果</h3><p>下载 trace、不可变 evidence ZIP 与企业验收指标，缺失指标明确标注未测量。</p><code>ETag · X-Evidence-SHA256 · scorecard</code></article>
</div>
""",
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="vg-head"><h2>快速调用</h2><span>本机默认 127.0.0.1:8787</span></div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "API 与工作台复用同一用户、工作区、项目及授权数据源；账户初始化接口不会随服务公开。"
    )
    task_payload: dict[str, Any] = {
        "project_id": project.project_id,
        "goal": "审核这批工业视觉数据并交付可追溯证据",
        "source_kind": project.source_kind.value,
    }
    if project.source_kind is DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY:
        sources = SERVICE.list_local_source_authorizations(
            user.user_id, project.workspace_id
        )
        task_payload["source_id"] = sources[0].source_id if sources else "{source_id}"
    st.code(
        f"""curl -X POST http://127.0.0.1:8787/v1/tasks \\
  -H "X-Actor-User-Id: {user.user_id}" \\
  -H "Idempotency-Key: my-batch-001" \\
  -H "Content-Type: application/json" \\
  -d '{json.dumps(task_payload, ensure_ascii=False, separators=(",", ":"))}' """,
        language="bash",
    )
    st.code(
        """# Poll and deliver
GET /v1/tasks/{task_id}
GET /v1/tasks/{task_id}/plan
GET /v1/tasks/{task_id}/preflight
POST /v1/tasks/{task_id}/reverifications
GET /v1/tasks/{task_id}/lineage
POST /v1/tasks/{task_id}/interventions
GET /v1/tasks/{task_id}/interventions
GET /v1/tasks/{task_id}/events
GET /v1/tasks/{task_id}/trace
GET /v1/tasks/{task_id}/evidence
GET /v1/tasks/{task_id}/industrial-delivery
POST /v1/tasks/{task_id}/industrial-incidents
GET /v1/tasks/{task_id}/industrial-incidents
GET /v1/tasks/{task_id}/industrial-incidents/{case_id}
POST /v1/tasks/{task_id}/industrial-incidents/{case_id}/decisions
POST /v1/tasks/{task_id}/industrial-incidents/{case_id}/resume
POST /v1/tasks/{task_id}/capa-cases
GET /v1/tasks/{task_id}/capa-cases
GET /v1/tasks/{task_id}/capa-cases/{case_id}
POST /v1/tasks/{task_id}/capa-cases/{case_id}/approval
POST /v1/tasks/{task_id}/capa-cases/{case_id}/execute
GET /v1/tasks/{task_id}/capa-cases/{case_id}/outcome-assessment
GET /v1/tasks/{task_id}/release-readiness
POST /v1/tasks/{task_id}/annotation-exports/cvat
POST /v1/tasks/{task_id}/annotation-imports
GET /v1/tasks/{task_id}/annotation-roundtrips
GET /v1/tasks/{task_id}/acceptance-scorecard

# Authorize and discover server-local industrial data
POST /v1/data-sources/local-authorizations
GET /v1/data-sources?workspace_id={workspace_id}
GET /v1/data-sources/{source_id}
GET /v1/data-sources/{source_id}/authorization-events
POST /v1/data-sources/{source_id}/revocations

# Discover the contract
GET /docs
GET /openapi.json""",
        language="http",
    )
    st.markdown(
        '<div class="vg-boundary">当前 Header 仅用于本地成员关系与工作区隔离演示，不是登录认证、API Key 或生产 IAM。API 默认只绑定本机，未开放 CORS，也不接受任意模型端点、密钥或本地文件路径。</div>',
        unsafe_allow_html=True,
    )


def _load_synthetic_visual_proof() -> tuple[dict[str, Any] | None, str | None]:
    initial_result_path = (
        SYNTHETIC_VISUAL_ROOT / "evidence" / "initial" / "gate_result.json"
    )
    repaired_result_path = (
        SYNTHETIC_VISUAL_ROOT / "evidence" / "repaired" / "gate_result.json"
    )
    initial_image_path = (
        SYNTHETIC_VISUAL_ROOT / "dataset" / "batch" / "images" / "q-blur.png"
    )
    repaired_image_path = (
        SYNTHETIC_VISUAL_ROOT / "repaired_batch" / "images" / "q-blur.png"
    )
    required = (
        initial_result_path,
        repaired_result_path,
        initial_image_path,
        repaired_image_path,
    )
    if not all(path.is_file() for path in required):
        return None, "Synthetic-v3 视觉证明资产不完整，已停止展示。"
    try:
        initial = GateResult.model_validate_json(
            initial_result_path.read_text(encoding="utf-8")
        )
        repaired = GateResult.model_validate_json(
            repaired_result_path.read_text(encoding="utf-8")
        )
        low_sharpness = next(
            finding for finding in initial.findings if finding.code == "LOW_SHARPNESS"
        )
        if any(finding.code == "LOW_SHARPNESS" for finding in repaired.findings):
            raise ValueError("the repaired proof still contains LOW_SHARPNESS")
        initial_sha256 = hashlib.sha256(initial_image_path.read_bytes()).hexdigest()
        repaired_sha256 = hashlib.sha256(repaired_image_path.read_bytes()).hexdigest()
    except (OSError, StopIteration, ValueError, ValidationError):
        return None, "Synthetic-v3 视觉证明未通过结构与结果校验，已停止展示。"
    return (
        {
            "initial": initial,
            "repaired": repaired,
            "finding": low_sharpness,
            "initial_image_path": initial_image_path,
            "repaired_image_path": repaired_image_path,
            "initial_sha256": initial_sha256,
            "repaired_sha256": repaired_sha256,
        },
        None,
    )


def _render_reviewer_case_cockpit() -> None:
    st.markdown(
        """
<div class="vg-casebar">
  <b>LOCAL AUTHORIZED CASE</b><span>Parent → Child</span><span class="hold">HOLD</span>
  <span>Root cause · 未确立</span><span>Owner · Quality Manager</span>
  <span class="safe">No device control · Human decision only</span>
</div>
<div class="vg-case-grid">
  <section class="vg-case-panel">
    <small>CASE VERSION TREE</small>
    <div class="vg-version"><b>Parent Case · v1</b><span>49 findings · evidence frozen</span></div>
    <div class="vg-version"><b>Named CAPA Decision</b><span>49/49 plan · exact evidence binding</span></div>
    <div class="vg-version current"><b>Child Case · v2</b><span>33 findings · 43 responsibilities open</span></div>
  </section>
  <section class="vg-case-panel middle">
    <small>AGENT INVESTIGATION WORKSPACE</small>
    <div class="vg-investigation">
      <div class="vg-fact"><small>VERIFIED CHANGE</small><b>Findings 49 → 33</b><span>数据整改产生局部改善，但不等于恢复。</span></div>
      <div class="vg-fact"><small>DECISION EFFECT</small><b>6 closed / 43 open</b><span>只有通过 Child Run 关闭条件的责任项才记为关闭。</span></div>
      <div class="vg-hypotheses">
        <div class="vg-hypothesis"><b>数据质量问题</b><span class="supported">部分支持</span></div>
        <div class="vg-hypothesis"><b>视觉方案 / 工艺窗口冲突</b><span class="conflict">尚未关闭</span></div>
        <div class="vg-hypothesis"><b>物理重采或扩大候选池</b><span class="open">缺少证据</span></div>
      </div>
    </div>
  </section>
  <section class="vg-case-panel">
    <small>GOVERNED PROFILE</small>
    <div class="vg-profile-row"><span>Planner</span><b>GATED</b></div>
    <div class="vg-profile-row"><span>Tool access</span><b>READ ONLY</b></div>
    <div class="vg-profile-row"><span>Evidence</span><b>HASH BOUND</b></div>
    <div class="vg-profile-row"><span>Production</span><b>HUMAN ONLY</b></div>
    <div class="vg-profile-row"><span>Next action</span><b>INVESTIGATE</b></div>
  </section>
</div>
<div class="vg-humanbar">
  <strong>Human Decision Bar · Reviewer snapshot is read-only</strong>
  <span class="primary">继续 HOLD</span><span>补充证据</span><span>转专业调查</span><span>选择 CAPA</span>
</div>
""",
        unsafe_allow_html=True,
    )
    st.caption(
        "该工作台摘要来自本地授权 RC3 `_05` 的脱敏统计，不展示原图、类别名、文件名或私有路径；它不是客户验收、生产恢复或官方提交回执。"
    )

    st.markdown(
        '<div class="vg-head"><h2>父子案件演进</h2><span>不覆盖父证据 · 每一步都有独立责任边界</span></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        """
<div class="vg-provenance">
  <div class="vg-provenance-node"><small>01 · PARENT</small><b>Gate · RECAPTURE</b><span>49 findings<br>父来源与父 Evidence 保持只读</span></div>
  <div class="vg-provenance-node"><small>02 · HUMAN</small><b>具名 CAPA 决定</b><span>绑定方案、授权、规则与责任队列</span></div>
  <div class="vg-provenance-node"><small>03 · DERIVED</small><b>私有派生版本</b><span>180 images / 60 masks<br>不回写父来源</span></div>
  <div class="vg-provenance-node"><small>04 · CHILD</small><b>同合同独立复验</b><span>33 findings<br>只有 6 项满足关闭条件</span></div>
  <div class="vg-provenance-node"><small>05 · PACKET</small><b>转人工调查</b><span>43 responsibilities open<br>production_release=false</span></div>
</div>
""",
        unsafe_allow_html=True,
    )


def _render_synthetic_visual_proof() -> None:
    st.markdown(
        '<div class="vg-head"><h2>让确定性工具结果可见</h2><span>Synthetic-v3 合成工程样例 · 不冒充工厂效果</span></div>',
        unsafe_allow_html=True,
    )
    proof, error = _load_synthetic_visual_proof()
    if proof is None:
        st.warning(error or "Synthetic-v3 视觉证明不可用。")
        return

    finding = proof["finding"]
    evidence = dict(finding.evidence)
    before, after = st.columns(2, gap="large")
    with before:
        st.image(
            str(proof["initial_image_path"]),
            caption=(
                "整改前 · LOW_SHARPNESS · "
                f"Laplacian variance {evidence['sharpness']:.4f} < "
                f"{evidence['minimum']:.1f}"
            ),
            width="stretch",
        )
    with after:
        st.image(
            str(proof["repaired_image_path"]),
            caption="整改副本 · LOW_SHARPNESS 已关闭 · 原来源未覆盖",
            width="stretch",
        )

    result_columns = st.columns(4)
    result_columns[0].metric("初始裁决", proof["initial"].decision)
    result_columns[1].metric("复验裁决", proof["repaired"].decision)
    result_columns[2].metric("注入问题", 12)
    result_columns[3].metric("合成闭环 F1", "1.00")
    st.caption(
        "图像来自仓库内冻结的 Synthetic-v3 公开合成夹具。该对比证明工具与整改复验路径可运行，不证明真实产线精度、客户 KPI 或模型效果。"
    )

    st.markdown(
        """
<div class="vg-algorithm-grid">
  <div class="vg-algorithm"><small>IMAGE QUALITY</small><b>亮度 + Laplacian 方差</b><span>解码、尺寸、平均亮度与清晰度阈值由确定性数值计算，不由 LLM 猜测。</span></div>
  <div class="vg-algorithm"><small>DUPLICATE LEAKAGE</small><b>SHA-256 + dHash / Hamming</b><span>精确重复用字节哈希；近似重复用感知指纹、汉明距离与缩略图差值复核。</span></div>
  <div class="vg-algorithm"><small>ANNOTATION</small><b>Mask 形状与前景比例</b><span>解码标注并核对尺寸、缺失、前景占比与样本合同，不使用语言模型估算几何。</span></div>
  <div class="vg-algorithm"><small>GOVERNANCE</small><b>合同、权限与来源哈希</b><span>来源 profile、工具白名单和人工权限一旦漂移，旧裁决停止复用。</span></div>
</div>
""",
        unsafe_allow_html=True,
    )

    raw_frame = {
        "schema": "visiondata-gate.synthetic-visual-frame.v1",
        "source": "Synthetic-v3 public fixture",
        "sample_id": "q-blur",
        "image_sha256": proof["initial_sha256"],
        "replacement_sha256": proof["repaired_sha256"],
        "measurement": {
            "mean_luma": evidence["mean_luma"],
            "laplacian_variance": evidence["sharpness"],
        },
        "contract": {"minimum_laplacian_variance": evidence["minimum"]},
        "initial_result": finding.code,
        "recheck_result": "PASS_NO_LOW_SHARPNESS_FINDING",
    }
    with st.expander("查看脱敏原始测量帧与哈希"):
        st.code(
            json.dumps(raw_frame, ensure_ascii=False, indent=2),
            language="json",
        )


def _render_ecosystem_compatibility() -> None:
    st.markdown(
        '<div class="vg-head"><h2>接入已有工业栈</h2><span>实现、合同验证、外部连接与 Roadmap 分开标识</span></div>',
        unsafe_allow_html=True,
    )
    st.dataframe(
        [
            {
                "能力层": "核心复用合同",
                "接口": "Site Pack · Evidence Schema · Rule Pack · REST API",
                "状态": "IMPLEMENTED",
                "边界": "本地代码与测试可验证",
            },
            {
                "能力层": "标注往返",
                "接口": "CVAT · FiftyOne",
                "状态": "LOCAL_CONTRACT_VALIDATED",
                "边界": "外部服务默认 NOT_CONNECTED",
            },
            {
                "能力层": "数据格式适配",
                "接口": "COCO · YOLO · Labelme",
                "状态": "PLANNED_NOT_IMPLEMENTED",
                "边界": "不能宣称已支持",
            },
            {
                "能力层": "实验系统适配",
                "接口": "MLflow · DVC",
                "状态": "PLANNED_NOT_IMPLEMENTED",
                "边界": "尚无真实 Adapter 或连接回执",
            },
        ],
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "VisionData Gate 作为已有流水线前的安全门禁；文件格式解析、SDK 存在和生产系统连接是三个不同层级。"
    )


def _render_reviewer_mode() -> None:
    release, error = _load_public_release()
    if release is None:
        st.title("评审模式")
        st.error(error or "公开评审证据不可用。")
        st.caption("系统不会在证据缺失、哈希不一致或结构校验失败时展示推测性结果。")
        return

    manifest = release.manifest
    namespaces = manifest["evidence_namespaces"]
    omni = namespaces["Omni-180-v1"]
    arch = namespaces["ArchBench-v2"]
    scenario_receipt = release.scenario_delivery_receipt
    proof_ladder = scenario_receipt["proof_ladder"]
    observed_pilot = scenario_receipt["observed_pilot"]
    current_gate_result, current_gate_receipt = _load_external_gate_result()
    dynamic_benchmark, dynamic_benchmark_error = _load_dynamic_benchmark()
    st.markdown(
        f"""
<section class="vg-review-hero">
  <div class="vg-review-badges"><span>LOCAL / ON-PREM</span><span>HUMAN-GOVERNED</span><span>冻结 RC2 · {_e(manifest["release_id"])}</span><span>NO DEVICE CONTROL</span></div>
  <h1>换型后视觉异常处置与方案复验 Agent</h1>
  <p>面向换型、视觉方案或数据版本变化后的 NG 异常，把图像、标注、批次、工单、工艺与视觉方案证据汇入同一个版本化案件。Agent 按证据缺口调查，具名人员决定 CAPA，Child Run 独立复验；局部改善不会被自动写成生产恢复。</p>
  <div class="vg-review-proof">
    <div><small>冻结公开 Pilot 分母</small><b>{_e(omni["selected_image_count"])}</b></div>
    <div><small>证据触发 Replan / Worker</small><b>{_e(observed_pilot["replan_count"])} / {_e(omni["worker_count"])}</b></div>
    <div><small>Finding → 责任工单</small><b>{_e(omni["finding_count"])} → {_e(omni["work_order_count"])}</b></div>
    <div><small>冻结裁决 · 规则检查 {_e(observed_pilot["rule_check_count"])} / {_e(observed_pilot["rule_check_count"])}</small><b>{_e(observed_pilot["decision"])}</b></div>
  </div>
</section>
""",
        unsafe_allow_html=True,
    )
    st.caption(
        "本页首屏数字来自冻结 RC2 公开快照，不会被当前开发运行改写。下方受控证据卡单独展示显式挂载的最新 GateResult。"
    )

    _render_reviewer_case_cockpit()
    _render_synthetic_visual_proof()
    _render_ecosystem_compatibility()

    st.markdown(
        '<div class="vg-head"><h2>当前受控产品 Gate</h2><span>与冻结 RC2 分开标识</span></div>',
        unsafe_allow_html=True,
    )
    _render_external_gate_panel(current_gate_result, current_gate_receipt)
    if current_gate_result is not None:
        st.caption(
            "该卡只读取经结构校验的脱敏 GateResult；初裁、动态派发与产品事件须在同一任务的 trace/evidence 中核验。"
        )

    st.markdown(
        '<div class="vg-head"><h2>先讲应用：谁在什么流程里得到什么结果</h2><span>明确用户 · 明确触发 · 可交付闭环</span></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        """
<div class="vg-story-grid">
  <article class="vg-story-card"><small>01 · TARGET USER</small><h3>质量负责人 / 视觉算法工程师</h3><p>换型或视觉方案变化后，需要把 NG 异常、方案版本、工艺证据和整改责任收敛到同一个案件。</p></article>
  <article class="vg-story-card"><small>02 · OPERATIONAL PAIN</small><h3>解释竞争，整改不等于恢复</h3><p>证据失效、工艺偏移、视觉漂移和数据问题可能同时成立；局部指标改善无法自动关闭根因责任。</p></article>
  <article class="vg-story-card"><small>03 · DELIVERED RESULT</small><h3>决定 + 责任队列 + 独立复验</h3><p>系统交付版本化案件、确定性测量、具名人工决定、Child Run 和可独立复算的审计材料。</p></article>
</div>
""",
        unsafe_allow_html=True,
    )

    proof_cards = [
        ("01 · IMPLEMENTED", "implemented", ""),
        ("02 · PUBLIC PILOT", "public_pilot", "public"),
        ("03 · EXTERNAL", "external_validation", "next"),
    ]
    proof_html: list[str] = []
    for index, key, tone in proof_cards:
        level = proof_ladder[key]
        items = level.get("facts", level.get("items", []))
        list_html = "".join(f"<li>{_e(item)}</li>" for item in items)
        proof_html.append(
            f'<article class="vg-proof-level {_e(tone)}">'
            f'<div class="vg-proof-top"><span class="vg-proof-index">{_e(index)}</span>'
            f'<span class="vg-proof-chip">{_e(level["status"])}</span></div>'
            f"<h3>{_e(level['label'])}</h3><p>{_e(level['scope'])}</p>"
            f"<ul>{list_html}</ul></article>"
        )
    st.markdown(
        '<div class="vg-head"><h2>冻结 RC2 三级证明</h2><span>实现证据 · 数据实跑 · 外部验收</span></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="vg-proof-ladder">{"".join(proof_html)}</div>'
        f'<div class="vg-proof-callout">{_e(scenario_receipt["interpretation"])}</div>',
        unsafe_allow_html=True,
    )
    receipt_bytes = canonical_json_bytes(scenario_receipt)
    download_col, note_col = st.columns([0.34, 0.66])
    with download_col:
        st.download_button(
            "下载场景交付凭证 JSON",
            data=receipt_bytes,
            file_name=SCENARIO_DELIVERY_FILENAME,
            mime="application/json",
            key="download_scenario_delivery_receipt",
        )
    with note_col:
        st.caption(
            "凭证将场景、三级证明、180 张固定样本实跑结果、288 条对照实验与源证据 SHA-256 固定在同一份可机读合同中。"
        )

    st.markdown(
        '<div class="vg-head"><h2>一条完整任务闭环</h2><span>从 NG 异常到具名决定与独立复验</span></div>',
        unsafe_allow_html=True,
    )
    loop_steps = [
        ("01", "异常输入", "换型、方案与 NG 证据"),
        ("02", "Evidence Gate", "资格、来源与确定性测量"),
        ("03", "竞争假设", "支持、反证与证据缺口"),
        ("04", "人工决定", "HOLD、补证或选择 CAPA"),
        ("05", "Child Run", "私有派生版本、同合同复验"),
        ("06", "Decision Packet", "责任队列、lineage 与哈希"),
    ]
    loop_html = "".join(
        f'<div class="vg-loop-step"><small>{_e(index)}</small><b>{_e(title)}</b><span>{_e(detail)}</span></div>'
        for index, title, detail in loop_steps
    )
    st.markdown(f'<div class="vg-loop">{loop_html}</div>', unsafe_allow_html=True)

    st.markdown(
        '<div class="vg-head"><h2>核心 Agent 行为：证据触发重规划</h2><span>不是永远运行固定 DAG</span></div>',
        unsafe_allow_html=True,
    )
    canvas_html = build_reviewer_canvas(
        release.dynamic_leader_plan,
        release.omni_gate_result,
        release.omni_gate_receipt,
        height=470,
    )
    canvas_src = "data:text/html;base64," + base64.b64encode(
        canvas_html.encode("utf-8")
    ).decode("ascii")
    st.iframe(canvas_src, height=470)
    st.caption(
        "冻结 RC2：180 张固定公开图像完成 Policy Gate；当前 RC3 已将 4,464 张源树接入授权声明与只读 profile，但 Policy Gate 固定分母仍为 180，不是全量认证。"
    )

    branch_copy = {
        item["task_id"]: (item["trigger_statement"], item["dynamic_action"])
        for item in observed_pilot["dynamic_triggers"]
    }
    branch_rows = []
    for task in release.dynamic_leader_plan["dynamic_tasks"]:
        trigger, result = branch_copy.get(
            task["task_id"],
            (
                str(task.get("trigger", "中间证据")),
                str(task.get("decision_effect", "补证并复判")),
            ),
        )
        branch_rows.append(
            {
                "证据触发": trigger,
                "动态动作": result,
                "调度时机": "首次裁决之后",
                "状态": "完成",
            }
        )
    st.dataframe(branch_rows, hide_index=True, width="stretch")

    st.markdown(
        '<div class="vg-head"><h2>ArchBench-v2：先排除“多角色越多越好”</h2><span>同输入 · 同合同 · 同工具 · 同 Judge</span></div>',
        unsafe_allow_html=True,
    )
    labels = {
        "traditional_pipeline": "传统流水线",
        "single_agent": "单 Agent",
        "multi_agent": "多 Agent",
    }
    arch_rows = []
    for key in ("traditional_pipeline", "single_agent", "multi_agent"):
        summary = release.architecture_benchmark["summaries"][key]
        arch_rows.append(
            {
                "架构": labels[key],
                "记录数": summary["record_count"],
                "错误放行率": f"{summary['error_release_rate']:.0%}",
                "任务成功率": f"{summary['task_success_rate']:.0%}",
                "扰动稳定率": f"{summary['perturbation_stability_rate']:.0%}",
                "F1": f"{summary['mean_f1']:.2f}",
                "相对计算单元": f"{summary['mean_relative_compute_units']:.0f}",
            }
        )
    st.dataframe(arch_rows, hide_index=True, width="stretch")
    st.markdown(
        f'<div class="vg-negative"><b>诚实负结论：</b>在 {_e(arch["record_count"])} 条固定 SOP 记录中，传统流水线、单 Agent 与多 Agent 的质量、成功率和扰动稳定性相同；多 Agent 必要性未被支持。项目因此把多 Agent 的使用边界收窄到“中间证据改变下一步任务”——也就是上面的动态补证，而不是用角色数量包装固定流程。</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "本实验的 actual model calls 与模型费用均为 0；token units 只是输入规模代理，时延仅为本机观测，不是生产 SLO。"
    )

    st.markdown(
        '<div class="vg-head"><h2>RC3 DynamicBench-v1：固定分母验证动态触发</h2><span>12 正例 · 12 负例 · 四架构同协议</span></div>',
        unsafe_allow_html=True,
    )
    if dynamic_benchmark_error:
        st.warning(dynamic_benchmark_error)
    elif dynamic_benchmark is None:
        st.info(
            "RC3 DynamicBench-v1 私有回执尚未挂载；冻结 RC2/ArchBench 证据仍可独立核验。"
        )
    else:
        denominators = dynamic_benchmark["fixed_denominators"]
        summaries = dynamic_benchmark["summaries"]
        dynamic_summary = summaries["dynamic_leader"]
        fixed_summary = summaries["fixed_multi_agent"]
        single_summary = summaries["single_agent"]
        metric_columns = st.columns(4)
        metric_columns[0].metric("同协议记录", denominators["record_count"])
        metric_columns[1].metric(
            "动态正例 / 负例",
            f"{denominators['positive_fixture_count']} / {denominators['negative_fixture_count']}",
        )
        metric_columns[2].metric(
            "Dynamic P / R",
            f"{dynamic_summary['dynamic_trigger_precision']:.0%} / {dynamic_summary['dynamic_trigger_recall']:.0%}",
        )
        avoided_calls = (
            fixed_summary["redundant_or_duplicate_tool_call_count"]
            - dynamic_summary["redundant_or_duplicate_tool_call_count"]
        )
        metric_columns[3].metric("避免无效补证", avoided_calls)

        dynamic_labels = {
            "traditional_pipeline": "传统静态流水线",
            "single_agent": "单 Agent",
            "fixed_multi_agent": "固定多 Agent",
            "dynamic_leader": "Dynamic Leader",
        }
        dynamic_rows = []
        for architecture in (
            "traditional_pipeline",
            "single_agent",
            "fixed_multi_agent",
            "dynamic_leader",
        ):
            summary = summaries[architecture]
            precision = summary["dynamic_trigger_precision"]
            dynamic_rows.append(
                {
                    "架构": dynamic_labels[architecture],
                    "触发 Precision": (
                        f"{precision:.0%}"
                        if precision is not None
                        else "未定义（无正预测）"
                    ),
                    "触发 Recall": f"{summary['dynamic_trigger_recall']:.0%}",
                    "动态例错误放行率": f"{summary['incorrect_release_rate']:.0%}",
                    "证据覆盖率": f"{summary['evidence_coverage_rate']:.0%}",
                    "无效 / 重复调用": summary[
                        "redundant_or_duplicate_tool_call_count"
                    ],
                    "本机 P95 ms": f"{summary['latency_ms_p95']:.4f}",
                }
            )
        st.dataframe(dynamic_rows, hide_index=True, width="stretch")
        st.markdown(
            '<div class="vg-negative"><b>固定边界结论：</b>'
            "单 Agent 与 Dynamic Leader 在这组确定性触发任务上的质量持平；"
            f"Dynamic Leader 相比固定多 Agent 少做 {avoided_calls} 次无效补证，但本机 P95 "
            f"{dynamic_summary['latency_ms_p95']:.4f} ms 没有快过单 Agent "
            f"{single_summary['latency_ms_p95']:.4f} ms。传统静态流水线在 12/12 动态正例上错误放行。"
            "该结果只证明编排触发语义，不是工业模型精度或对未运行竞品的数值领先。</div>",
            unsafe_allow_html=True,
        )
        benchmark_sha256 = hashlib.sha256(
            canonical_json_bytes(dynamic_benchmark)
        ).hexdigest()
        st.caption(
            "RC3 私有回执已通过结构、内嵌哈希和固定分母复算；"
            f"actual model calls = {dynamic_benchmark['actual_model_call_count']}，"
            f"模型状态 = {dynamic_benchmark['model_execution_status']}，"
            f"回执 SHA-256 = {benchmark_sha256}。"
        )

    st.markdown(
        '<div class="vg-head"><h2>应用与 Infra 双向促进</h2><span>前台价值决定后台能力，后台证据反哺应用可信度</span></div>',
        unsafe_allow_html=True,
    )
    left, right = st.columns(2)
    with left:
        st.markdown(
            '<div class="vg-card"><small>APPLICATION → INFRA</small><h3>异常处置闭环提出工程约束</h3><p>竞争假设、跨角色证据、具名责任、私有派生版本和独立复验，推动底层具备 typed case、动态调度、权限白名单与失败关闭。</p></div>',
            unsafe_allow_html=True,
        )
    with right:
        st.markdown(
            '<div class="vg-card"><small>INFRA → APPLICATION</small><h3>可信后台让决定可复核</h3><p>统一 evidence_span、reason_trace、规则检查和审计封套，使应用不只“给建议”，而是交付责任队列、父子案件和可复核的质量决定。</p></div>',
            unsafe_allow_html=True,
        )

    with st.expander("查看已完成证据与下一阶段扩展范围"):
        scope = manifest["claim_scope"]
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**已完成并可复验**")
            for item in scope["verified"]:
                st.markdown(f"- {_e(item)}")
        with c2:
            st.markdown("**下一阶段外部验收**")
            for item in scope["external_pending"]:
                st.markdown(f"- {_e(item)}")
        st.info(
            "外部验收是把已完成闭环扩展到客户、工厂和生产环境所需的下一层证据；不反向否定当前工程实现和 Omni-180-v1 实跑。AgentTeams v1.2.2 静态契约为 PASS，transport 状态为 OPEN，连接状态保持 mapped_not_connected。"
        )


def _render_trust(user: Any, workspace: Any) -> None:
    st.title("安全与权限")
    st.caption("当前本地部署的访问范围、数据连接和发布权限。")
    rows = [
        (
            "REST API",
            "可用",
            "工作区、项目、任务、状态与审核凭证；默认仅绑定本机",
        ),
        (
            "工作区隔离",
            "本地模式",
            "SQLite 成员关系与跨工作区隐藏；不等于登录认证或生产 IAM",
        ),
        (
            "审核凭证",
            "完整性校验",
            "下载前复核 SHA-256；路径越界、跨空间或内容篡改均拒绝交付",
        ),
        (
            "整改往返",
            "本地合同可用",
            "CVAT/FiftyOne 导出、回传哈希校验与同合同复验已实现；外部服务仍未连接",
        ),
        ("发布权限", "人工授权", "本地结果不等于生产恢复；生产写回保持阻断"),
    ]
    st.dataframe(
        [{"能力或证据": a, "状态": b, "范围说明": c} for a, b, c in rows],
        hide_index=True,
        width="stretch",
    )
    st.markdown(
        '<div class="vg-head"><h2>数据源连接策略</h2><span>默认 fail closed</span></div>',
        unsafe_allow_html=True,
    )
    health = SERVICE.health()
    local_state = health.data_sources.get(
        DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY.value, "not_connected"
    )
    authorized_sources = SERVICE.list_local_source_authorizations(
        user.user_id, workspace.workspace_id
    )
    active_source_count = sum(item.status == "active" for item in authorized_sources)
    if active_source_count:
        local_status = f"已授权 {active_source_count} 个"
        local_body = "服务器允许目录与操作员声明已验证；运行前仍会复核源 profile 漂移。"
        local_tone = "ok"
    elif local_state == "connected_readonly_allowlist":
        local_status = "允许目录已配置"
        local_body = "尚无工作区授权回执；未完成用途与权利声明前不能创建真实数据任务。"
        local_tone = "warn"
    else:
        local_status = "未连接"
        local_body = "服务器未配置允许目录，任何本地路径请求都会失败关闭。"
        local_tone = "warn"
    cols = st.columns(3)
    sources = [
        ("合成演示数据", "已连接", "程序化生成，适合工程复现与评审演示。", "ok"),
        ("本地授权目录", local_status, local_body, local_tone),
        (
            "外部驻留数据",
            "未连接",
            "只保留引用接口，不把受控数据复制进公开包。",
            "warn",
        ),
    ]
    for column, (title, status, body, tone) in zip(cols, sources, strict=True):
        column.markdown(
            f'<div class="vg-card"><span class="vg-status {tone}"><i class="vg-dot"></i>{status}</span><h3>{title}</h3><p>{body}</p></div>',
            unsafe_allow_html=True,
        )
    st.markdown(
        '<div class="vg-head"><h2>整改系统适配</h2><span>接口可用不等于外部已连接</span></div>',
        unsafe_allow_html=True,
    )
    c1, c2 = st.columns(2)
    c1.markdown(
        '<div class="vg-card"><span class="vg-status warn"><i class="vg-dot"></i>合同可用 · 未连接</span><h3>CVAT</h3><p>已实现工单导出、外部任务 ID 绑定约束、修订字节回传、哈希校验与同合同复验；需真实 endpoint 探测回执后才标记连接。</p></div>',
        unsafe_allow_html=True,
    )
    c2.markdown(
        '<div class="vg-card"><span class="vg-status warn"><i class="vg-dot"></i>合同可用 · 未连接</span><h3>FiftyOne</h3><p>已实现 sample patch 合同与相同回传验证；核心安装不依赖 FiftyOne，环境自行提供该库时才执行本地可用性探测。</p></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="vg-boundary"><b>权限边界：</b>本地 PASS 只表示当前数据版本满足冻结 Gate 合同；它不代表异常根因关闭、模型有效、数据权属成立、产线安全或生产恢复。生产写回始终需要真实授权主体。</div>',
        unsafe_allow_html=True,
    )
    with st.expander("查看评审与外部连接状态"):
        st.markdown(
            "AgentTeams 当前为 `mapped_not_connected`。外部受控数据、真实客户验证、生产部署与赛事平台提交均不由本地运行结果自动成立；完整状态见 `docs/REVIEWER_READINESS_MATRIX.md` 与 `claim_scope_receipt.json`。"
        )


def main() -> None:
    _bootstrap()
    page, user, workspace, projects, project = _render_sidebar()
    if workspace is None:
        st.title("开始使用 VisionData Gate")
        st.info("请在侧栏切换到已有工作区用户，或创建一个本地演示工作区。")
        return
    if page == "工作台":
        _render_overview(user, workspace, projects, project)
    elif page == "异常处置":
        _render_industrial_incidents(user, workspace)
    elif page == "评审模式":
        _render_reviewer_mode()
    elif page == "项目":
        _render_projects(user, workspace, projects)
    elif page == "数据源":
        _render_data_sources(user, workspace)
    elif page == "审核记录":
        _render_runs(user, workspace)
    elif page == "能力目录":
        _render_skills()
    elif page == "API 接入":
        _render_api(user, project)
    else:
        _render_trust(user, workspace)


if __name__ == "__main__":
    main()
