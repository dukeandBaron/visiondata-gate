"""Reviewer-safe visual canvas for one industrial incident case."""

from __future__ import annotations

from html import escape

from .industrial_incident import IndustrialIncidentCase


_PHASE_LABELS = {
    "PLAN": "理解异常",
    "ACT": "专业补证",
    "OBSERVE": "汇总证据",
    "EVALUATE": "规则裁决",
    "INTERRUPT": "人工决定",
}


def _safe(value: object) -> str:
    return escape(str(value), quote=True)


def build_incident_canvas(
    case: IndustrialIncidentCase,
    *,
    height: int = 440,
) -> str:
    """Return a standalone HTML canvas without raw source paths or hidden reasoning."""

    phases = []
    for step in case.loop_steps:
        tone = (
            "paused"
            if step.status == "PAUSED"
            else "stopped"
            if step.status == "STOPPED"
            else "done"
        )
        phases.append(
            "<div class='phase {tone}'>"
            "<span>{sequence:02d}</span><b>{label}</b><small>{actor}</small>"
            "<p>{summary}</p></div>".format(
                tone=tone,
                sequence=step.sequence,
                label=_safe(_PHASE_LABELS.get(step.phase, step.phase)),
                actor=_safe(step.actor),
                summary=_safe(step.summary),
            )
        )

    workers = [
        action
        for action in case.agent_actions
        if action.dynamic and action.status in {"COMPLETED", "STOPPED"}
    ]
    verified_worker_roles = {item.worker_role for item in case.worker_receipts}
    worker_chips = (
        "".join(
            "<span class='worker {tone}'><i></i>{role}<em>{status}</em></span>".format(
                tone="blocked" if item.status == "STOPPED" else "",
                role=_safe(item.agent_role.replace("Agent", " Agent")),
                status=_safe(
                    "预算停止"
                    if item.status == "STOPPED"
                    else "回执已验签"
                    if item.agent_role in verified_worker_roles
                    else "历史版本"
                ),
            )
            for item in workers
        )
        or "<span class='empty'>本轮无需增派专业 Worker</span>"
    )

    active_hypotheses = [
        item for item in case.hypotheses if item.status.value != "REJECTED"
    ]
    hypothesis_cards = "".join(
        "<article><div><b>{statement}</b><span>{status}</span></div>"
        "<p>{test}</p></article>".format(
            statement=_safe(item.statement),
            status=_safe(item.status.value),
            test=_safe(item.next_discriminating_test),
        )
        for item in active_hypotheses[:4]
    )

    fixture = case.opcua_connection_status == "OPC_UA_FIXTURE_REPLAY_ONLY"
    source_badge = (
        "过程证据：FIXTURE，仅验证闭环"
        if fixture
        else "过程证据：离线只读导出，未连接端点"
    )
    receipt_badge = (
        f"{len(case.worker_receipts)} 个 Worker 回执已验签"
        if case.worker_receipts
        else "历史案件：无独立 Worker 回执"
    )
    progress_badge = (
        "取得进展"
        if case.progress_ledger is not None and case.progress_ledger.progress_made
        else "无进展，等待重规划"
        if case.progress_ledger is not None
        else ""
    )
    progress_badge_html = (
        f'<span class="badge">{_safe(progress_badge)}</span>' if progress_badge else ""
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
*{{box-sizing:border-box}}html,body{{margin:0;background:transparent;color:#19221f;font-family:Inter,"SF Pro Display","PingFang SC","Microsoft YaHei",sans-serif}}
.canvas{{height:{height}px;padding:18px 20px;border:1px solid #dfe8e3;border-radius:24px;background:radial-gradient(circle at 8% 0%,#e8fff2 0,transparent 34%),linear-gradient(145deg,#fbfdfc,#f3f7f5);box-shadow:0 18px 50px rgba(30,64,48,.08);overflow:hidden}}
.top{{display:flex;align-items:flex-start;justify-content:space-between;gap:18px;margin-bottom:16px}}.eyebrow{{font-size:11px;letter-spacing:.12em;color:#63736a;text-transform:uppercase}}h1{{font-size:21px;line-height:1.2;margin:5px 0 0}}.badges{{display:flex;gap:7px;flex-wrap:wrap;justify-content:flex-end}}.badge{{font-size:11px;padding:7px 10px;border:1px solid #cfe0d6;background:#fff;border-radius:999px;color:#425148}}.badge.strong{{background:#163d2c;color:#fff;border-color:#163d2c}}
.flow{{position:relative;display:grid;grid-template-columns:repeat(5,1fr);gap:9px;margin-bottom:15px}}.flow:before{{content:"";position:absolute;left:7%;right:7%;top:22px;height:2px;background:#d6e1db}}.phase{{position:relative;min-height:106px;padding:13px 12px 10px;border:1px solid #dce6e1;border-radius:16px;background:rgba(255,255,255,.9);box-shadow:0 6px 16px rgba(33,63,49,.04)}}.phase>span{{display:grid;place-items:center;width:22px;height:22px;border-radius:50%;background:#1b714b;color:white;font-size:10px;position:relative;z-index:2;margin-bottom:7px}}.phase b{{display:block;font-size:13px}}.phase small{{display:block;color:#708078;font-size:9px;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.phase p{{font-size:10px;line-height:1.45;color:#526158;margin:7px 0 0}}.phase.paused{{border-color:#e6c371;background:#fffaf0}}.phase.paused>span{{background:#b87911}}.phase.stopped{{border-color:#e7b1ad;background:#fff7f6}}.phase.stopped>span{{background:#a83f38}}
.lower{{display:grid;grid-template-columns:.9fr 1.1fr;gap:12px}}.panel{{border:1px solid #dfe8e3;border-radius:16px;background:rgba(255,255,255,.78);padding:12px 13px;min-height:145px}}.panel h2{{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:#63736a;margin:0 0 9px}}.workers{{display:flex;flex-wrap:wrap;gap:7px}}.worker{{display:inline-flex;align-items:center;gap:5px;padding:6px 8px;border-radius:10px;background:#edf8f2;color:#245a40;font-size:10px}}.worker i{{width:6px;height:6px;background:#2c9a67;border-radius:50%}}.worker em{{font-style:normal;color:#708078;margin-left:2px}}.worker.blocked{{background:#fff1ef;color:#873a34}}.worker.blocked i{{background:#c75148}}.empty{{font-size:11px;color:#738077}}
.hypotheses{{display:grid;grid-template-columns:1fr 1fr;gap:7px}}article{{padding:8px 9px;border-radius:11px;background:#f6f9f7;border:1px solid #e6ece8}}article div{{display:flex;align-items:flex-start;gap:8px;justify-content:space-between}}article b{{font-size:10px;line-height:1.3}}article span{{font-size:8px;color:#7b5e16;background:#fff0bf;border-radius:99px;padding:3px 5px;white-space:nowrap}}article p{{font-size:9px;color:#66736c;margin:4px 0 0;line-height:1.35}}
.foot{{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:11px;font-size:10px;color:#66736c}}.foot strong{{color:#9b640b}}.foot code{{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;background:#ecf1ee;padding:4px 7px;border-radius:7px;color:#4d5c54}}
@media(max-width:820px){{.canvas{{height:auto;min-height:{height}px;overflow:visible}}.flow{{grid-template-columns:1fr 1fr}}.flow:before{{display:none}}.lower{{grid-template-columns:1fr}}}}
</style>
</head>
<body><main class="canvas">
  <section class="top"><div><div class="eyebrow">Incident loop · immutable v{case.case_version}</div><h1>证据驱动的换型异常处置</h1></div><div class="badges"><span class="badge strong">{_safe(case.status.value)}</span><span class="badge">{_safe(source_badge)}</span><span class="badge">{_safe(receipt_badge)}</span>{progress_badge_html}</div></section>
  <section class="flow">{"".join(phases)}</section>
  <section class="lower"><div class="panel"><h2>按证据动态增派</h2><div class="workers">{worker_chips}</div></div><div class="panel"><h2>仍在竞争的解释</h2><div class="hypotheses">{hypothesis_cards}</div></div></section>
  <section class="foot"><span><strong>人工中断：</strong>{_safe(case.recommendation_reason)}</span><code>{_safe(case.case_id)}</code></section>
</main></body></html>"""


__all__ = ["build_incident_canvas"]
