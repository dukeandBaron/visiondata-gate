"""Single-file, offline HTML reporting for VisionData Gate."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

from .contracts import EvaluationResult, GateResult
from .evidence import canonical_json_text, sha256_bytes


def _text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _e(value: Any) -> str:
    return escape(_text(value), quote=True)


def _list_items(values: list[str], *, empty: str = "无") -> str:
    if not values:
        return f'<li class="muted">{_e(empty)}</li>'
    return "".join(f"<li>{_e(value)}</li>" for value in values)


def render_offline_html(
    result: GateResult,
    evaluation: EvaluationResult | None = None,
    *,
    title: str = "VisionData Gate 可审计报告",
) -> str:
    """Render a deterministic, dependency-free HTML report.

    No JavaScript, remote fonts, or remote images are emitted. All dynamic
    content is HTML-escaped, including evidence supplied by tools.
    """

    decision_class = result.decision.value.lower()
    metric_rows = "".join(
        f"<tr><th>{_e(name)}</th><td>{_e(value)}</td></tr>"
        for name, value in sorted(result.metrics.items())
    )

    finding_rows: list[str] = []
    for finding in sorted(
        result.findings, key=lambda item: (item.finding_id, item.code)
    ):
        evidence_json = canonical_json_text(finding.evidence, trailing_newline=False)
        finding_rows.append(
            "<tr>"
            f"<td><code>{_e(finding.finding_id)}</code></td>"
            f"<td><code>{_e(finding.code)}</code></td>"
            f'<td><span class="severity {_e(finding.severity.value)}">'
            f"{_e(finding.severity.value)}</span></td>"
            f"<td>{_e(finding.tool)}</td>"
            f"<td>{_e(', '.join(sorted(finding.sample_ids)) or '批次级')}</td>"
            f"<td>{_e(finding.summary)}</td>"
            f"<td>{_e(finding.recommended_action)}</td>"
            f"<td><code>{_e(evidence_json)}</code></td>"
            "</tr>"
        )
    if not finding_rows:
        finding_rows.append('<tr><td colspan="8" class="muted">无 findings</td></tr>')

    tool_rows: list[str] = []
    for trace in sorted(result.tool_trace, key=lambda item: item.sequence):
        tool_rows.append(
            "<tr>"
            f"<td>{trace.sequence}</td>"
            f"<td>{_e(trace.tool)}</td>"
            f"<td>{_e(trace.status)}</td>"
            f"<td><code>{_e(trace.input_sha256)}</code></td>"
            f"<td><code>{_e(trace.result_sha256)}</code></td>"
            f"<td>{_e(', '.join(sorted(trace.finding_ids)) or '—')}</td>"
            f"<td>{_e(trace.error or '—')}</td>"
            "</tr>"
        )
    if not tool_rows:
        tool_rows.append('<tr><td colspan="7" class="muted">无工具轨迹</td></tr>')

    opinion_cards: list[str] = []
    for opinion in sorted(
        result.council_trace.independent_opinions, key=lambda item: item.role_id
    ):
        axes = " · ".join(
            f"{axis}={opinion.confidence_axes[axis]}" for axis in ("E", "T", "A", "M")
        )
        opinion_cards.append(
            '<article class="opinion">'
            f"<h3>{_e(opinion.display_name)}</h3>"
            f'<p class="muted"><code>{_e(opinion.role_id)}</code> · {_e(opinion.focus)}</p>'
            f"<p><strong>建议：</strong>{_e(opinion.recommendation.value)}</p>"
            f"<p><strong>置信轴：</strong>{_e(axes)}</p>"
            f"<p><strong>质询：</strong>{_e(opinion.challenge)}</p>"
            f"<p><strong>主张</strong></p><ul>{_list_items(opinion.claims)}</ul>"
            f"<p><strong>局限</strong></p><ul>{_list_items(opinion.limitations)}</ul>"
            "</article>"
        )
    if not opinion_cards:
        opinion_cards.append('<p class="muted">无 AI Council 意见</p>')

    work_order_rows: list[str] = []
    for order in sorted(result.work_orders, key=lambda item: item.work_order_id):
        work_order_rows.append(
            "<tr>"
            f"<td><code>{_e(order.work_order_id)}</code></td>"
            f"<td>{_e(order.action)}</td>"
            f"<td>{_e(order.priority.value)}</td>"
            f"<td>{_e(', '.join(sorted(order.reason_codes)))}</td>"
            f"<td>{_e(', '.join(sorted(order.sample_ids)) or '批次级')}</td>"
            f"<td>{_e(order.status)}</td>"
            "</tr>"
        )
    if not work_order_rows:
        work_order_rows.append('<tr><td colspan="6" class="muted">无工单</td></tr>')

    evaluation_section = ""
    if evaluation is not None:
        evaluation_rows = "".join(
            f"<tr><th>{_e(name)}</th><td>{_e(value)}</td></tr>"
            for name, value in sorted(
                evaluation.model_dump(
                    mode="json", exclude={"schema_version", "batch_id", "notes"}
                ).items()
            )
        )
        evaluation_section = (
            '<section id="evaluation"><h2>隐藏真值评估</h2>'
            f'<table class="kv">{evaluation_rows}</table>'
            f"<h3>评估说明</h3><ul>{_list_items(evaluation.notes)}</ul></section>"
        )

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:">
  <title>{_e(title)}</title>
  <style>
    :root {{ color-scheme: light; --blue:#0b6cff; --gold:#d9b431; --ink:#101114; --muted:#5c6573; --line:#d7dee8; --panel:#f5f7fa; }}
    * {{ box-sizing: border-box; }}
    body {{ margin:0; color:var(--ink); background:white; font:15px/1.55 Arial,"Microsoft YaHei",sans-serif; }}
    main {{ max-width:1180px; margin:0 auto; padding:32px 28px 64px; }}
    h1 {{ margin:0 0 8px; font-size:34px; }} h2 {{ margin-top:34px; border-bottom:2px solid var(--ink); padding-bottom:8px; }}
    h3 {{ margin:0 0 8px; }} p {{ margin:8px 0; }} code {{ overflow-wrap:anywhere; }}
    .eyebrow {{ color:var(--blue); font-weight:700; letter-spacing:.12em; }}
    .decision {{ display:inline-block; margin:14px 0; padding:10px 18px; border-radius:999px; color:white; background:var(--ink); font-weight:800; }}
    .decision.pass {{ background:#087f5b; }} .decision.quarantine,.decision.recapture {{ background:#9c5d00; }} .decision.defer {{ background:#5d6470; }}
    .notice {{ border-left:6px solid var(--gold); padding:14px 18px; background:#fff9df; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:14px; }}
    .opinion {{ border:1px solid var(--line); border-radius:12px; padding:16px; background:var(--panel); }}
    .muted {{ color:var(--muted); }}
    .table-wrap {{ overflow-x:auto; border:1px solid var(--line); border-radius:10px; }}
    table {{ width:100%; border-collapse:collapse; }} th,td {{ padding:9px 10px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }}
    th {{ background:#eef2f7; }} .kv th {{ width:34%; }}
    .severity {{ font-weight:700; }} .severity.critical,.severity.high {{ color:#a40000; }} .severity.medium {{ color:#8a5600; }}
    footer {{ margin-top:42px; padding-top:18px; border-top:1px solid var(--line); color:var(--muted); }}
    @media print {{ main {{ max-width:none; padding:10mm; }} .table-wrap {{ overflow:visible; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <div class="eyebrow">VISIONDATA GATE · AUDIT REPORT</div>
    <h1>{_e(title)}</h1>
    <p>run <code>{_e(result.run_id)}</code> · batch <code>{_e(result.batch_id)}</code> · contract <code>{_e(result.contract_id)}</code></p>
    <div class="decision {decision_class}">{_e(result.decision.value)}</div>
    <p><strong>确定性理由：</strong>{_e(result.decision_reason)}</p>
    <div class="notice"><strong>边界：</strong>{_e(result.boundary_notice)}</div>
  </header>

  <section id="scope"><h2>运行与责任范围</h2>
    <table class="kv">
      <tr><th>输入 SHA-256</th><td><code>{_e(result.input_sha256)}</code></td></tr>
      <tr><th>Policy</th><td>{_e(result.policy_version)}</td></tr>
      <tr><th>发布范围</th><td>{_e(result.release_scope)}</td></tr>
      <tr><th>生产前真实授权主体</th><td>{"必须" if result.human_authority_required_before_production else "不需要"}</td></tr>
      <tr><th>Council backend</th><td>{_e(result.council_trace.backend)}</td></tr>
      <tr><th>同源披露</th><td>{_e(result.council_trace.shared_model_disclosure)}</td></tr>
    </table>
  </section>

  <section id="metrics"><h2>门禁指标</h2><table class="kv">{metric_rows}</table></section>

  <section id="findings"><h2>Findings</h2><div class="table-wrap"><table>
    <thead><tr><th>ID</th><th>Code</th><th>级别</th><th>工具</th><th>样本</th><th>摘要</th><th>动作</th><th>证据</th></tr></thead>
    <tbody>{"".join(finding_rows)}</tbody>
  </table></div></section>

  <section id="tools"><h2>白名单工具轨迹</h2><div class="table-wrap"><table>
    <thead><tr><th>#</th><th>工具</th><th>状态</th><th>输入 SHA</th><th>结果 SHA</th><th>Finding</th><th>错误</th></tr></thead>
    <tbody>{"".join(tool_rows)}</tbody>
  </table></div></section>

  <section id="council"><h2>AI Expert Council（非真人专家）</h2><div class="grid">{"".join(opinion_cards)}</div>
    <h3>交叉质询</h3><ul>{_list_items(result.council_trace.cross_examination)}</ul>
    <h3>未解决异议</h3><ul>{_list_items(result.council_trace.unresolved_objections)}</ul>
  </section>

  <section id="work-orders"><h2>工单</h2><div class="table-wrap"><table>
    <thead><tr><th>ID</th><th>动作</th><th>优先级</th><th>原因</th><th>样本</th><th>状态</th></tr></thead>
    <tbody>{"".join(work_order_rows)}</tbody>
  </table></div></section>

  {evaluation_section}
  <footer>本文件为单文件离线报告；不加载外部字体、脚本、图片或分析服务。哈希证明完整性，不等于数据授权、真人签名或法律认证。</footer>
</main>
</body>
</html>
"""
    return html.replace("\r\n", "\n")


def offline_html_bytes(
    result: GateResult,
    evaluation: EvaluationResult | None = None,
    *,
    title: str = "VisionData Gate 可审计报告",
) -> bytes:
    """Return UTF-8 report bytes with a stable trailing newline."""

    html = render_offline_html(result, evaluation, title=title)
    if not html.endswith("\n"):
        html += "\n"
    return html.encode("utf-8")


def write_offline_html(
    path: str | Path,
    result: GateResult,
    evaluation: EvaluationResult | None = None,
    *,
    title: str = "VisionData Gate 可审计报告",
) -> str:
    """Write an offline HTML report and return its SHA-256 digest."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = offline_html_bytes(result, evaluation, title=title)
    destination.write_bytes(data)
    return sha256_bytes(data)


__all__ = ["offline_html_bytes", "render_offline_html", "write_offline_html"]
