from __future__ import annotations

import base64
import csv
import hashlib
import html
import io
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

import streamlit as st
from pydantic import ValidationError

from visiondata_gate.contracts import GateResult
from visiondata_gate.evidence import canonical_json_bytes
from visiondata_gate.product_models import (
    CreateProjectRequest,
    CreateTaskRequest,
    CreateUserRequest,
    CreateWorkspaceRequest,
    DataSourceKind,
    TaskExecutionStatus,
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
    "CROSS_SPLIT_EXACT_DUPLICATE": "跨数据集精确重复",
    "CROSS_SPLIT_NEAR_DUPLICATE": "跨数据集近似重复",
    "DECODE_FAILURE": "图像无法解码",
    "EXACT_DUPLICATE": "批次内精确重复",
    "GOVERNANCE_SCOPE_GAP": "治理范围缺口",
    "INVALID_DIMENSIONS": "图像尺寸不合规",
    "LOW_SHARPNESS": "清晰度不足",
    "METADATA_COUNT_DRIFT": "元数据计数漂移",
    "MISSING_ANNOTATION": "缺少标注",
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
DECISION_EXPLANATIONS = {
    "PASS": "在冻结的沙箱实验训练池合同下通过；生产发布仍需真实授权主体审批。",
    "RECAPTURE": "当前证据触发整改门槛；完成工单后必须按同一规则重新复验。",
    "QUARANTINE": "当前批次需要隔离处理，不能进入实验训练池。",
    "DEFER": "证据或必需能力不足，系统已安全暂缓且没有推测性放行。",
}

EXTERNAL_GATE_RESULT_ENV = "VISIONDATA_UI_EXTERNAL_GATE_RESULT"
PUBLIC_RELEASE_DIR_ENV = "VISIONDATA_UI_RELEASE_DIR"

st.set_page_config(
    page_title="VisionData Gate · 工业视觉数据治理 Agent",
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
.vg-entry-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:1rem; }
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
    <div class="vg-live-stat"><small>工具回执</small><b>{summary["tool_count"]}/5</b></div>
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
            '<div class="vg-brand"><div class="vg-logo">V</div><div><b>VisionData Gate</b><span>工业视觉数据治理 Agent</span></div></div>',
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
            "评审模式",
            "项目",
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
  <p><code>{_e(task.task_id)}</code> · {_e(_scenario_label(task.scenario_profile))} · 演示批次 {task.seed} · {task.updated_at[:19].replace("T", " ")}</p>
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
        '<div class="vg-head"><h2>创建审核任务</h2><span>提交后进入持久化运行队列</span></div>',
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
        goal = st.text_area(
            "审核目标",
            value="审核工业视觉数据批次能否进入实验训练池；若阻断，生成整改任务并在同一规则下复验。",
            height=105,
            key="task_goal",
        )
        c1, c2 = st.columns(2)
        seed = int(
            c1.number_input(
                "演示批次编号",
                min_value=0,
                max_value=99_999_999,
                value=20_260_809,
                step=1,
                key="task_seed",
            )
        )
        profile = c2.selectbox(
            "规则包",
            [ScenarioProfile.INDUSTRIAL, ScenarioProfile.GENERIC],
            format_func=lambda item: (
                "工业视觉治理" if item is ScenarioProfile.INDUSTRIAL else "通用数据治理"
            ),
            key="task_profile",
        )
        selected_tools = st.multiselect(
            "检查能力",
            tools,
            default=tools,
            format_func=_tool_label,
            key="task_allowed_tools",
        )
        submitted = st.form_submit_button(
            "创建并运行审核任务", type="primary", width="stretch"
        )
    if submitted:
        try:
            task = SERVICE.create_task(
                user.user_id,
                CreateTaskRequest(
                    project_id=selected_project_id,
                    goal=goal,
                    seed=seed,
                    scenario_profile=profile,
                    source_kind=DataSourceKind.SYNTHETIC_DEMO,
                    allowed_tools=selected_tools,
                ),
                auto_start=True,
            )
        except (ValidationError, ProductStoreError, ProductServiceError) as error:
            st.error(f"任务未创建：{str(error)[:240]}")
        else:
            st.session_state["selected_task_id"] = task.task_id
            st.session_state["_pending_nav"] = "审核记录"
            st.success(f"任务已进入运行队列：{task.task_id}")
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
    evidence_state = "受控真实证据已挂载" if external_result else "演示工作区"
    st.markdown(
        f"""
<section class="vg-hero">
  <div><div class="vg-kicker">工业视觉数据治理与发布 Agent</div><h1>让每个数据批次<br>带着证据进入训练</h1><p>从审核目标理解、并行检查和动态补证，到整改工单、同规则复验与凭证交付，全部绑定同一个任务 ID。面向视觉算法工程师和工业数据团队，不是聊天框，而是一条可调用、可复核的业务闭环。</p></div>
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
                f'<div class="vg-card"><small>合成演示数据 · {_e(_scenario_label(item.scenario_profile))}</small><h3>{_e(item.name)}</h3><p>{_e(item.description or "尚未填写项目说明")} · {count} 次运行</p></div>',
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


def _timeline(status: TaskExecutionStatus) -> str:
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
    initial_rows = _load_task_csv(user, task, "initial/evidence_matrix.csv")
    repaired_rows = _load_task_csv(user, task, "repaired/evidence_matrix.csv")
    initial_result = _load_task_payload(user, task, "initial/gate_result.json") or {}
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
    rows_by_finding: dict[str, list[dict[str, str]]] = {}
    for row in initial_rows:
        rows_by_finding.setdefault(row.get("finding_id", ""), []).append(row)
    for finding_id, matrix_rows in rows_by_finding.items():
        row = matrix_rows[0]
        finding = finding_by_id.get(row.get("finding_id", ""), {})
        order_ids = list(
            dict.fromkeys(
                item.get("work_order_ids", "")
                for item in matrix_rows
                if item.get("work_order_ids")
            )
        )
        orders = [order_by_id.get(order_id, {}) for order_id in order_ids]
        finding_code = row.get("finding_code", "")
        sample_ids = finding.get("sample_ids") or [
            value for value in row.get("sample_ids", "").split("|") if value
        ]
        actions = list(
            dict.fromkeys(
                _action_label(order.get("action", ""))
                for order in orders
                if order.get("action")
            )
        )
        recheck = "仍需处理" if finding_code in repaired_codes else "复验已消除"
        recheck_tone = "warn" if finding_code in repaired_codes else "ok"
        cards.append(
            f"""
<article class="vg-evidence-item">
  <div class="vg-evidence-top"><small>{_e(_tool_label(row.get("tool", "")))}</small><span class="vg-status {recheck_tone}"><i class="vg-dot"></i>{_e(recheck)}</span></div>
  <h3>{_e(_finding_label(finding_code))}</h3>
  <p><b>证据对象</b> · {_e("、".join(sample_ids) if sample_ids else "批次级规则")}</p>
  <p><b>整改动作</b> · {_e("、".join(actions) if actions else "按工单处理")}{_e(f" · {len(order_ids)} 张关联工单" if len(order_ids) > 1 else "")}</p>
</article>
"""
        )
    st.markdown(
        '<div class="vg-evidence-grid">' + "".join(cards) + "</div>",
        unsafe_allow_html=True,
    )
    st.caption(
        "以上映射来自已验 SHA-256 的 evidence ZIP；完整 finding ID、evidence_span、reason_trace 与规则检查保留在下载凭证和高级审计中。"
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
        artifacts = [
            "claim_scope_receipt.json",
            "runtime_contract_audit.json",
            "skill_qualification_receipt.json",
            "tool_replay_receipt.json",
            "tool_ablation_receipt.json",
            "proof_index.json",
        ]
        for name in artifacts:
            st.download_button(
                f"下载 {name}",
                SERVICE.read_evidence_zip_bytes(user.user_id, task.task_id, name),
                file_name=name,
                mime="application/json",
                key=f"download_{task.task_id}_{name}",
                width="stretch",
            )


def _render_task_detail(user: Any, task: Any) -> None:
    st.markdown(
        f'<div class="vg-head"><h2>任务详情</h2><span>{_e(task.task_id)}</span></div>',
        unsafe_allow_html=True,
    )
    st.markdown(_timeline(task.execution_status), unsafe_allow_html=True)
    st.caption(f"目标：{task.goal}")
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
    initial = _load_task_payload(user, task, "initial/gate_result.json") or {}
    repaired = _load_task_payload(user, task, "repaired/gate_result.json") or {}
    decision = task.final_decision or "UNKNOWN"
    decision_reason = DECISION_EXPLANATIONS.get(
        decision, "同规则复验已完成，详情见审核凭证。"
    )
    tool_labels = "、".join(_tool_label(item) for item in task.allowed_tools)
    st.markdown(
        f"""
<section class="vg-detail-hero">
  <div class="vg-decision {_e(decision.lower())}"><small>最终审核结论</small><b>{_e(decision)}</b><p>{_e(decision_reason)}</p></div>
  <div class="vg-detail-metrics">
    <div class="vg-detail-metric"><small>首轮问题</small><b>{len(initial.get("findings", []))}</b></div>
    <div class="vg-detail-metric"><small>整改任务</small><b>{len(initial.get("work_orders", []))}</b></div>
    <div class="vg-detail-metric"><small>复验后问题</small><b>{len(repaired.get("findings", []))}</b></div>
    <div class="vg-detail-config"><b>冻结配置</b> · {_e(_scenario_label(task.scenario_profile))} · 演示批次 {_e(task.seed)}<br>{_e(tool_labels)}</div>
  </div>
</section>
""",
        unsafe_allow_html=True,
    )
    st.caption(
        "门禁结论与系统运行状态分开保存；DEFER 是正确完成的暂缓决定，不等于系统异常。"
    )
    tabs = st.tabs(["证据链", "发现的问题", "整改任务", "审核凭证"])
    with tabs[0]:
        _render_evidence_chain(user, task)
    with tabs[1]:
        findings = initial.get("findings", [])
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
    with tabs[2]:
        orders = initial.get("work_orders", [])
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
    with tabs[3]:
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
  <article class="vg-entry"><small>03 · DELIVER</small><h3>交付可验证结果</h3><p>完成后下载原始 trace 和不可变 evidence ZIP，并用响应摘要复核完整性。</p><code>ETag · X-Evidence-SHA256</code></article>
</div>
""",
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="vg-head"><h2>快速调用</h2><span>本机默认 127.0.0.1:8787</span></div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "API 服务默认使用工作台已创建的本地演示对象；账户初始化接口不会随服务公开。"
    )
    st.code(
        f'''curl -X POST http://127.0.0.1:8787/v1/tasks \\
  -H "X-Actor-User-Id: {user.user_id}" \\
  -H "Idempotency-Key: my-batch-001" \\
  -H "Content-Type: application/json" \\
  -d '{{"project_id":"{project.project_id}","goal":"审核这批数据并交付证据"}}' ''',
        language="bash",
    )
    st.code(
        """# Poll and deliver
GET /v1/tasks/{task_id}
GET /v1/tasks/{task_id}/events
GET /v1/tasks/{task_id}/trace
GET /v1/tasks/{task_id}/evidence

# Discover the contract
GET /docs
GET /openapi.json""",
        language="http",
    )
    st.markdown(
        '<div class="vg-boundary">当前 Header 仅用于本地成员关系与工作区隔离演示，不是登录认证、API Key 或生产 IAM。API 默认只绑定本机，未开放 CORS，也不接受任意模型端点、密钥或本地文件路径。</div>',
        unsafe_allow_html=True,
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
    st.markdown(
        f"""
<section class="vg-review-hero">
  <div class="vg-review-badges"><span>赛道二 · 无界应用</span><span>AI+工业制造</span><span>Release {_e(manifest["release_id"])}</span><span>可复现 · 可审计</span></div>
  <h1>工业视觉数据治理与发布 Agent</h1>
  <p>围绕“工业视觉批次进入沙箱实验训练池前”这一明确任务设计，并已跑通本地可验证闭环：批次检查、风险研判、证据触发补证、整改工单、同合同复验与审核凭证交付。可信 Agent Infra 让每一步可追踪、可失败关闭、可复用。</p>
  <div class="vg-review-proof">
    <div><small>固定公开图像已 Gate</small><b>{_e(omni["selected_image_count"])}</b></div>
    <div><small>重规划 / 动态 Worker</small><b>{_e(observed_pilot["replan_count"])} / {_e(omni["worker_count"])}</b></div>
    <div><small>问题 → 工单</small><b>{_e(omni["finding_count"])} → {_e(omni["work_order_count"])}</b></div>
    <div><small>批次结论 · 规则检查 {_e(observed_pilot["rule_check_count"])} / {_e(observed_pilot["rule_check_count"])}</small><b>{_e(observed_pilot["decision"])}</b></div>
  </div>
</section>
""",
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="vg-head"><h2>先讲应用：谁在什么流程里得到什么结果</h2><span>明确用户 · 明确触发 · 可交付闭环</span></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        """
<div class="vg-story-grid">
  <article class="vg-story-card"><small>01 · TARGET USER</small><h3>视觉算法工程师 / 数据治理团队</h3><p>在训练或评测前，需要确认图像、标注、划分、覆盖和治理证据是否满足同一批次合同。</p></article>
  <article class="vg-story-card"><small>02 · OPERATIONAL PAIN</small><h3>检查分散，整改与复验脱节</h3><p>多个脚本给出碎片化结果；同一样本可能出现冲突处置，问题无法稳定映射到负责人、工单和复验规则。</p></article>
  <article class="vg-story-card"><small>03 · DELIVERED RESULT</small><h3>结论 + 工单 + 可校验凭证</h3><p>系统交付 GateResult、整改工单、规则检查、证据矩阵与 SHA-256；完成修复后按原合同重新复验。</p></article>
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
        '<div class="vg-head"><h2>场景落地证明：我们已经做到哪一层</h2><span>实现证据 · 数据实跑 · 外部验收</span></div>',
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
        '<div class="vg-head"><h2>一条完整任务闭环</h2><span>从批次输入到结果交付</span></div>',
        unsafe_allow_html=True,
    )
    loop_steps = [
        ("01", "理解目标", "合同、场景与权限"),
        ("02", "并行检查", "五类只读工具"),
        ("03", "动态补证", "中间证据触发"),
        ("04", "门禁裁决", "冻结规则失败关闭"),
        ("05", "整改复验", "保留副本、同一合同"),
        ("06", "证据交付", "矩阵、trace 与哈希"),
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
        "Omni-180-v1：180 张固定公开图像完成 Policy Gate；4,464 张源树仅完成结构/解码审计，不是全量 Gate 认证。"
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
        '<div class="vg-head"><h2>应用与 Infra 双向促进</h2><span>前台价值决定后台能力，后台证据反哺应用可信度</span></div>',
        unsafe_allow_html=True,
    )
    left, right = st.columns(2)
    with left:
        st.markdown(
            '<div class="vg-card"><small>APPLICATION → INFRA</small><h3>面向真实业务任务的闭环提出约束</h3><p>批次审核要求跨工具证据、冲突处置、工单责任、同规则复验和结果交付，推动底层具备 typed task、动态调度、权限白名单与失败关闭。</p></div>',
            unsafe_allow_html=True,
        )
    with right:
        st.markdown(
            '<div class="vg-card"><small>INFRA → APPLICATION</small><h3>可信后台让结果可采用</h3><p>统一 evidence_span、reason_trace、规则检查和 SHA-256，使应用不只“给建议”，而是交付可追踪的整改任务和可复核的 Gate 结论。</p></div>',
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


def _render_trust() -> None:
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
        ("发布权限", "人工授权", "本地 PASS 只进入沙箱实验训练池；生产写回保持阻断"),
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
    cols = st.columns(3)
    sources = [
        ("合成演示数据", "已连接", "程序化生成，适合工程复现与评审演示。", "ok"),
        ("本地授权目录", "未连接", "需确认权利主体、用途、驻留与脱敏范围。", "warn"),
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
        '<div class="vg-boundary"><b>权限边界：</b>本地 PASS 只表示该批次满足冻结合同并可进入沙箱实验训练池；它不代表产品合格、模型有效、数据已授权、产线安全或法律认证。生产写回始终需要真实授权主体。</div>',
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
    elif page == "评审模式":
        _render_reviewer_mode()
    elif page == "项目":
        _render_projects(user, workspace, projects)
    elif page == "审核记录":
        _render_runs(user, workspace)
    elif page == "能力目录":
        _render_skills()
    elif page == "API 接入":
        _render_api(user, project)
    else:
        _render_trust()


if __name__ == "__main__":
    main()
