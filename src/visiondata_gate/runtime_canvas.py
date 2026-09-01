"""Self-contained evidence-flow Canvas for the observable agent runtime."""

from __future__ import annotations

import html
import json
from collections.abc import Iterable

from .runtime_models import AgentTask, RuntimeStatus, RuntimeTrace


_PRIORITY = {
    RuntimeStatus.ERROR: 6,
    RuntimeStatus.WARNING: 5,
    RuntimeStatus.RUNNING: 4,
    RuntimeStatus.SUCCESS: 3,
    RuntimeStatus.SKIPPED: 2,
    RuntimeStatus.QUEUED: 1,
}


def _aggregate(tasks: Iterable[AgentTask]) -> str:
    values = list(tasks)
    if not values:
        return RuntimeStatus.QUEUED.value
    if all(task.status is RuntimeStatus.SUCCESS for task in values):
        return RuntimeStatus.SUCCESS.value
    return max(values, key=lambda task: _PRIORITY[task.status]).status.value


def _node_statuses(trace: RuntimeTrace | None) -> dict[str, str]:
    if trace is None:
        return {
            key: "queued"
            for key in (
                "trigger",
                "router",
                "memory",
                "planner",
                "gateway",
                "workers",
                "model",
                "council",
                "judge",
                "repair",
                "verify",
                "delivery",
            )
        }
    tasks = trace.tasks

    def select(fragment: str) -> list[AgentTask]:
        return [task for task in tasks if fragment in task.task_id]

    return {
        "trigger": "success" if trace.events else "queued",
        "router": _aggregate(select(".route")),
        "memory": _aggregate(select(".memory")),
        "planner": _aggregate(select(".plan")),
        "gateway": _aggregate(select(".tool.")),
        "workers": _aggregate(select(".tool.")),
        "model": (
            "warning"
            if trace.fallback_used
            else ("success" if trace.backend_connected else "queued")
        ),
        "council": _aggregate(select(".council")),
        "judge": _aggregate(
            [task for task in tasks if task.task_id == "initial.judge"]
        ),
        "repair": _aggregate(select("system.repair")),
        "verify": _aggregate(
            [task for task in tasks if task.task_id.startswith("verification.")]
        ),
        "delivery": _aggregate(select("system.delivery")),
    }


def _current_step(statuses: dict[str, str]) -> str:
    order = [
        "delivery",
        "verify",
        "repair",
        "judge",
        "council",
        "workers",
        "planner",
        "router",
        "trigger",
    ]
    running = next((key for key in order if statuses.get(key) == "running"), None)
    if running:
        return running
    return next(
        (key for key in order if statuses.get(key) in {"success", "warning", "error"}),
        "trigger",
    )


def build_runtime_canvas(trace: RuntimeTrace | None, *, height: int = 540) -> str:
    """Build a dependency-free Canvas that emphasizes evidence and decision flow."""

    statuses = _node_statuses(trace)
    recent_event = (
        trace.events[-1].summary if trace and trace.events else "等待任务进入运行时"
    )
    payload = {
        "statuses": statuses,
        "current": _current_step(statuses),
        "backend": trace.backend if trace else "等待运行",
        "scenario": (trace.scenario_profile.value if trace else "generic"),
        "events": len(trace.events) if trace else 0,
        "toolCalls": trace.tool_call_count if trace else 0,
        "modelCalls": trace.model_call_count if trace else 0,
        "contextTransfers": len(trace.context_transfers) if trace else 0,
        "decision": " → ".join(trace.judge_decisions)
        if trace and trace.judge_decisions
        else "未执行",
        "runId": trace.run_id if trace else "runtime-preview",
        "recentEvent": recent_event,
        "unresolved": len(trace.unresolved) if trace else 0,
        "agentteams": (
            {
                "team": trace.agentteams.team_name,
                "room": trace.agentteams.room_id,
                "connection": trace.agentteams.connection_status,
                "workerCount": len(trace.agentteams.worker_agent_ids),
                "skillCount": len(trace.agentteams.skills),
            }
            if trace and trace.agentteams
            else {
                "team": "VisionData Release Gate Team",
                "room": "room.visiondata-gate.runtime",
                "connection": "mapped_not_connected",
                "workerCount": 4,
                "skillCount": 5,
            }
        ),
    }
    data = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    escaped = {
        key: html.escape(str(value))
        for key, value in {
            "events": payload["events"],
            "tool_calls": payload["toolCalls"],
            "transfers": payload["contextTransfers"],
            "scenario": payload["scenario"],
            "decision": payload["decision"],
            "team": payload["agentteams"]["team"],
            "connection": payload["agentteams"]["connection"],
            "run_id": payload["runId"],
        }.items()
    }
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>
*{{box-sizing:border-box}} html,body{{margin:0;background:transparent;overflow:hidden;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif}}
.shell{{position:relative;height:{height}px;border:1px solid #dce3ee;border-radius:24px;background:linear-gradient(150deg,#fbfdff,#f2f6fc);box-shadow:0 18px 55px rgba(25,48,84,.08);overflow:hidden}}
canvas{{display:block;width:100%;height:100%}}
.top{{position:absolute;left:24px;right:24px;top:20px;display:flex;justify-content:space-between;gap:18px;align-items:flex-start;pointer-events:none}}
.eyebrow{{font-size:10px;letter-spacing:.17em;color:#1769e0;font-weight:800}} .title{{color:#172033;font-size:16px;font-weight:760;margin-top:5px}}
.subline{{color:#7b8798;font-size:10px;margin-top:6px}} .meta{{display:flex;gap:7px;flex-wrap:wrap;justify-content:flex-end;max-width:56%}}
.chip{{padding:6px 9px;border:1px solid #dfe5ee;border-radius:999px;background:rgba(255,255,255,.78);color:#687488;font-size:9px;backdrop-filter:blur(8px)}}
.detail{{position:absolute;left:24px;right:24px;bottom:17px;display:grid;grid-template-columns:minmax(0,1.55fr) repeat(3,minmax(86px,.35fr));gap:9px;pointer-events:none}}
.event,.stat{{border:1px solid #e0e5ed;border-radius:13px;background:rgba(255,255,255,.82);padding:9px 11px;min-width:0}}
.event small,.stat small{{display:block;color:#9098a5;font-size:8px;letter-spacing:.05em}} .event b{{display:block;color:#465267;font-size:10px;margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.stat b{{display:block;color:#172033;font-size:13px;margin-top:3px}} .boundary{{position:absolute;right:24px;bottom:82px;color:#8b94a2;font-size:8px;pointer-events:none}}
@media(max-width:640px){{.top{{left:16px;right:16px;top:15px}}.meta{{display:none}}.detail{{left:16px;right:16px;bottom:13px;grid-template-columns:1fr 1fr}}.event{{grid-column:1/-1}}.detail .stat:last-child{{display:none}}.boundary{{display:none}}}}
</style></head><body><div class="shell">
<canvas id="runtimeCanvas" role="img" aria-label="VisionData Gate Agent 证据流运行图"></canvas>
<div class="top"><div><div class="eyebrow">AUDITABLE AGENT RUNTIME / CANVAS</div><div class="title">Router · Workers · Model · Tools · Judge · Memory</div><div class="subline">{escaped["team"]} · {escaped["run_id"]}</div></div>
<div class="meta"><span class="chip">{escaped["scenario"]}</span><span class="chip">{escaped["connection"]}</span><span class="chip">事件 {escaped["events"]}</span><span class="chip">工具 {escaped["tool_calls"]}</span><span class="chip">Transfers {escaped["transfers"]}</span><span class="chip">裁决 {escaped["decision"]}</span></div></div>
<div class="detail"><div class="event"><small>最新可审计事件</small><b id="recent"></b></div><div class="stat"><small>当前节点</small><b id="current"></b></div><div class="stat"><small>证据移交</small><b>{escaped["transfers"]}</b></div><div class="stat"><small>未决事项</small><b id="unresolved"></b></div></div>
<div class="boundary">AgentTeams 映射状态与真实连接状态分开记录</div>
</div><script>
const DATA={data};
document.getElementById('recent').textContent=DATA.recentEvent;document.getElementById('unresolved').textContent=String(DATA.unresolved);
const stageLabels={{trigger:'任务进入',router:'路由分派',planner:'冻结计划',gateway:'工具网关',workers:'并行检查',memory:'证据记忆',model:'模型后端',council:'专家质询',judge:'规则裁决',repair:'整改工单',verify:'同规则复验',delivery:'凭证交付'}};
document.getElementById('current').textContent=stageLabels[DATA.current]||DATA.current;
const canvas=document.getElementById('runtimeCanvas'),ctx=canvas.getContext('2d');
const colors={{success:'#1b8a4a',running:'#1769e0',warning:'#c17a0c',error:'#c53b34',skipped:'#8e98a7',queued:'#c4cad3'}};
const nodes=[
{{id:'trigger',x:.08,y:.30,w:.13,h:.10,label:'任务进入',sub:'目标 · 权限 · 场景'}},{{id:'router',x:.25,y:.30,w:.13,h:.10,label:'路由分派',sub:'DAG · 依赖 · 预算'}},{{id:'planner',x:.42,y:.30,w:.13,h:.10,label:'冻结计划',sub:'规则包 · 工具白名单'}},{{id:'gateway',x:.59,y:.30,w:.13,h:.10,label:'工具网关',sub:'只读调用 · 失败语义'}},{{id:'workers',x:.78,y:.30,w:.17,h:.10,label:'并行检查',sub:'质量 · 泄漏 · 标注 · 覆盖'}},
{{id:'memory',x:.25,y:.58,w:.15,h:.10,label:'证据记忆',sub:'来源 · 版本 · 摘要'}},{{id:'model',x:.44,y:.58,w:.15,h:.10,label:'模型后端',sub:DATA.backend}},{{id:'council',x:.63,y:.58,w:.15,h:.10,label:'专家质询',sub:'角色假设 · 反方意见'}},{{id:'judge',x:.82,y:.58,w:.15,h:.10,label:'规则裁决',sub:'finding → rule check'}},
{{id:'repair',x:.50,y:.80,w:.14,h:.095,label:'整改工单',sub:'action · reason trace'}},{{id:'verify',x:.69,y:.80,w:.14,h:.095,label:'同规则复验',sub:'稳定性 · 反事实'}},{{id:'delivery',x:.87,y:.80,w:.14,h:.095,label:'凭证交付',sub:'trace · evidence · hash'}}];
const edges=[['trigger','router'],['router','planner'],['planner','gateway'],['gateway','workers'],['workers','council'],['router','memory'],['memory','council'],['model','council'],['council','judge'],['judge','repair'],['repair','verify'],['verify','delivery'],['delivery','memory']];
let W=0,H=0,dpr=1,hover=null;
function resize(){{const r=canvas.getBoundingClientRect();dpr=Math.min(devicePixelRatio||1,2);W=r.width;H=r.height;canvas.width=W*dpr;canvas.height=H*dpr;ctx.setTransform(dpr,0,0,dpr,0,0)}}
function geom(n){{return{{x:(n.x-n.w/2)*W,y:(n.y-n.h/2)*H,w:n.w*W,h:n.h*H}}}} function round(x,y,w,h,r){{ctx.beginPath();ctx.roundRect(x,y,w,h,r)}}
function center(id){{const g=geom(nodes.find(v=>v.id===id));return{{x:g.x+g.w/2,y:g.y+g.h/2}}}} function path(a,b){{const p=center(a),q=center(b),dx=q.x-p.x;return{{p,q,c1:{{x:p.x+dx*.48,y:p.y}},c2:{{x:q.x-dx*.48,y:q.y}}}}}}
function bx(s,t){{const u=1-t;return u*u*u*s.p.x+3*u*u*t*s.c1.x+3*u*t*t*s.c2.x+t*t*t*s.q.x}} function by(s,t){{const u=1-t;return u*u*u*s.p.y+3*u*u*t*s.c1.y+3*u*t*t*s.c2.y+t*t*t*s.q.y}}
function drawEdge(a,b,time,index){{const s=path(a,b);ctx.beginPath();ctx.moveTo(s.p.x,s.p.y);ctx.bezierCurveTo(s.c1.x,s.c1.y,s.c2.x,s.c2.y,s.q.x,s.q.y);ctx.strokeStyle='#d4dae4';ctx.lineWidth=1.2;ctx.stroke();const live=['success','running','warning'].includes(DATA.statuses[a])&&DATA.statuses[b]!=='queued';if(live){{const t=((time*.00012)+(index*.11))%1;ctx.beginPath();ctx.arc(bx(s,t),by(s,t),2.3,0,Math.PI*2);ctx.fillStyle=colors[DATA.statuses[b]]||colors.running;ctx.fill()}}}}
function drawNode(n){{const g=geom(n),status=DATA.statuses[n.id]||'queued',accent=colors[status],active=DATA.current===n.id,isHover=hover===n.id;ctx.save();ctx.shadowColor=active?'rgba(23,105,224,.22)':'rgba(28,45,70,.08)';ctx.shadowBlur=active?22:10;ctx.shadowOffsetY=5;round(g.x,g.y,g.w,g.h,14);ctx.fillStyle=active?'#eef5ff':'rgba(255,255,255,.96)';ctx.fill();ctx.shadowBlur=0;ctx.strokeStyle=active?accent:(isHover?accent:'#dfe4eb');ctx.lineWidth=active?1.7:1;ctx.stroke();ctx.fillStyle=accent;round(g.x+10,g.y+11,4,Math.max(17,g.h-22),3);ctx.fill();ctx.fillStyle='#192235';ctx.font='700 11px "Microsoft YaHei",system-ui';ctx.fillText(n.label,g.x+23,g.y+24);ctx.fillStyle='#7b8797';ctx.font='9px "Microsoft YaHei",system-ui';let sub=String(n.sub);if(sub.length>27)sub=sub.slice(0,26)+'…';ctx.fillText(sub,g.x+23,g.y+40);ctx.restore()}}
function frame(time){{ctx.clearRect(0,0,W,H);edges.forEach((e,i)=>drawEdge(e[0],e[1],time,i));nodes.forEach(drawNode);requestAnimationFrame(frame)}}
canvas.addEventListener('mousemove',e=>{{const r=canvas.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top;hover=null;for(const n of nodes){{const g=geom(n);if(x>=g.x&&x<=g.x+g.w&&y>=g.y&&y<=g.y+g.h)hover=n.id}}canvas.style.cursor=hover?'pointer':'default'}});window.addEventListener('resize',resize);resize();requestAnimationFrame(frame);
</script></body></html>"""


__all__ = ["build_runtime_canvas"]
