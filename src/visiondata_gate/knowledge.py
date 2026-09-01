"""Small, explicit semantic knowledge base used by the local agent runtime.

The cards are project policies and capability boundaries, not external industry
standards.  Retrieval is deliberately deterministic so every cited statement
can be reproduced without a network call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence

from .contracts import Finding
from .runtime_models import KnowledgeHit


@dataclass(frozen=True)
class KnowledgeCard:
    card_id: str
    title: str
    scope: str
    content: str
    keywords: tuple[str, ...]
    source_type: str = "project-policy"
    source_version: str = "2026-08-12"
    last_verified: str = "2026-08-12"
    permission_scope: str = "local-read-only"
    freshness: str = "frozen"


_CARDS = (
    KnowledgeCard(
        "policy.release-scope",
        "发布范围硬边界",
        "governance",
        "PASS 只允许批次进入 sandbox_experiment_training_pool；不代表产品合格、模型有效、数据授权或产线安全。",
        ("pass", "release", "scope", "sandbox", "生产", "发布", "边界"),
    ),
    KnowledgeCard(
        "policy.evidence-first",
        "证据优先原则",
        "governance",
        "Agent 的解释和建议不得创造检测数值；结论必须引用已执行工具的 finding、trace 或冻结合同。",
        ("evidence", "trace", "finding", "claim", "证据", "工具", "结论"),
    ),
    KnowledgeCard(
        "capability.image-quality",
        "图像采集质量能力",
        "image_quality",
        "图像质量 Worker 检查可解码性、尺寸、亮度范围和清晰度；异常默认生成补采工单。",
        ("decode", "dimension", "sharp", "blur", "luma", "quality", "图像", "补采"),
    ),
    KnowledgeCard(
        "capability.duplicate-leakage",
        "重复与跨划分泄漏能力",
        "duplicate_leakage",
        "重复泄漏 Worker 检查精确重复、近重复和跨 split 泄漏；命中后必须隔离并移除或重新划分。",
        ("duplicate", "leak", "split", "重复", "泄漏", "隔离", "划分"),
    ),
    KnowledgeCard(
        "capability.annotation",
        "标注结构完整性能力",
        "annotation_integrity",
        "标注 Worker 检查缺失标注、图像与 mask 尺寸一致性和面积边界；结构异常进入重标工单。",
        ("annotation", "mask", "label", "标注", "重标", "尺寸", "结构"),
    ),
    KnowledgeCard(
        "capability.coverage",
        "采集覆盖矩阵能力",
        "coverage_matrix",
        "覆盖 Worker 依据类别、视角、条件和 split 的冻结矩阵查找缺口；缺口只能通过补采或授权调整合同解决。",
        ("coverage", "cell", "category", "view", "condition", "覆盖", "视角", "补采"),
    ),
    KnowledgeCard(
        "policy.fail-closed",
        "失败关闭策略",
        "judge",
        "任何必需工具失败、跳过或高严重度证据不受支持时，Judge 必须输出 DEFER，不得复用历史成功结果。",
        ("error", "skipped", "unsupported", "defer", "失败", "跳过", "历史"),
    ),
    KnowledgeCard(
        "policy.repair-recheck",
        "同合同修复复验",
        "workflow",
        "工单完成后必须在同一数据合同和同一工具白名单下重新检测；只有复验结果可以支持后续 PASS。",
        ("repair", "recheck", "work order", "修复", "复验", "工单", "同合同"),
    ),
    KnowledgeCard(
        "policy.least-privilege",
        "工具最小权限",
        "security",
        "Worker 只能调用运行配置允许的只读检测工具；模型不能直接访问文件系统、修改合同或覆盖 Judge。",
        ("permission", "allowlist", "tool", "权限", "白名单", "文件", "judge"),
    ),
    KnowledgeCard(
        "policy.ai-role-disclosure",
        "AI 角色披露",
        "governance",
        "专家名称代表机器角色而非真人资质；同一模型的多个角色意见不是独立证据，多数票不能替代工具测量。",
        ("agent", "expert", "council", "专家", "角色", "真人", "模型", "投票"),
    ),
    KnowledgeCard(
        "policy.approval-handoff",
        "生产授权交接边界",
        "governance",
        "本地运行只产生沙箱资格与审计证据；生产写回、客户数据使用和正式发布必须由外部授权主体复核并留下独立回执。",
        (
            "approval",
            "handoff",
            "production",
            "authorize",
            "审批",
            "交接",
            "生产",
            "授权",
        ),
    ),
)


def _tokens(text: str) -> set[str]:
    lowered = text.lower()
    latin = set(re.findall(r"[a-z0-9_]+", lowered))
    chinese = set(re.findall(r"[\u4e00-\u9fff]{2,}", lowered))
    return latin | chinese


def retrieve_knowledge(
    query: str,
    findings: Sequence[Finding] | Iterable[Finding] = (),
    *,
    limit: int = 6,
) -> list[KnowledgeHit]:
    """Return deterministic policy/capability cards for one runtime context."""

    finding_list = list(findings)
    context = " ".join(
        [query]
        + [
            f"{item.code} {item.tool} {item.summary} {item.recommended_action}"
            for item in finding_list
        ]
    )
    context_tokens = _tokens(context)
    scored: list[tuple[float, KnowledgeCard]] = []
    for card in _CARDS:
        keyword_tokens = _tokens(" ".join(card.keywords))
        content_tokens = _tokens(f"{card.title} {card.scope} {card.content}")
        overlap = len(context_tokens & (keyword_tokens | content_tokens))
        scope_bonus = sum(
            2
            for item in finding_list
            if card.scope == item.tool or card.scope in item.code.lower()
        )
        governance_bonus = 1 if card.scope in {"governance", "judge"} else 0
        score = float(overlap + scope_bonus + governance_bonus)
        if score > 0:
            scored.append((score, card))
    scored.sort(key=lambda item: (-item[0], item[1].card_id))
    return [
        KnowledgeHit(
            card_id=card.card_id,
            title=card.title,
            scope=card.scope,
            excerpt=card.content,
            source=f"project-policy://{card.card_id}",
            score=score,
            source_type=card.source_type,
            source_version=card.source_version,
            last_verified=card.last_verified,
            permission_scope=card.permission_scope,
            freshness=card.freshness,
        )
        for score, card in scored[:limit]
    ]


def role_memory() -> dict[str, str]:
    """Stable role instructions shown in the memory center and model prompts."""

    return {
        "router": "识别工业数据发布意图，拒绝超出数据合同的任务。",
        "planner": "拆分依赖图并只选择白名单能力，不直接制造检测结论。",
        "quality_worker": "只报告可解码性、尺寸、亮度和清晰度工具证据。",
        "leakage_worker": "只报告重复、近重复和跨 split 泄漏证据。",
        "annotation_worker": "只报告标注缺失、结构和尺寸一致性证据。",
        "coverage_worker": "只报告冻结覆盖矩阵的缺口。",
        "council": "按角色解释、质询并引用证据，不把多角色同意当成独立事实。",
        "judge": "执行 fail-closed 冻结策略；AI 建议不能覆盖工具与合同。",
    }


__all__ = ["KnowledgeCard", "retrieve_knowledge", "role_memory"]
