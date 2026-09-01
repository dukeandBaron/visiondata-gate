"""Dependency-free Canvas for the evidence-triggered application story."""

from __future__ import annotations

import html
import json
from typing import Any

from .contracts import GateResult


def build_reviewer_canvas(
    dynamic_plan: dict[str, Any],
    gate_result: GateResult,
    omni_receipt: dict[str, Any],
    *,
    height: int = 470,
) -> str:
    """Render the fixed-tool wave and the three evidence-triggered branches."""

    branch_labels = {
        "cross-tool-conflict-adjudication": "冲突复核",
        "metadata-reconciliation": "元数据对账",
        "native-resolution-reconciliation": "分辨率分组补证",
    }
    tasks: list[dict[str, str]] = []
    for task in dynamic_plan.get("dynamic_tasks", []):
        branch = str(task.get("task_id", "")).removeprefix("followup.")
        tasks.append(
            {
                "id": branch,
                "label": branch_labels.get(branch, branch),
                "trigger": str(task.get("trigger", "中间证据触发")),
                "effect": str(task.get("decision_effect", "补充证据并复判")),
            }
        )
    payload = {
        "tasks": tasks,
        "decision": gate_result.decision.value,
        "findingCount": len(gate_result.findings),
        "workOrderCount": len(gate_result.work_orders),
        "sampleCount": int(omni_receipt.get("selected_image_count", 0)),
        "replanCount": int(dynamic_plan.get("replan_count", 0)),
        "staticTaskCount": int(dynamic_plan.get("static_task_count", 0)),
    }
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace(
        "</", "<\\/"
    )
    safe_decision = html.escape(gate_result.decision.value)
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>
*{{box-sizing:border-box}}html,body{{margin:0;background:transparent;overflow:hidden;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif}}
.shell{{position:relative;height:{height}px;border:1px solid #dce3ee;border-radius:26px;background:radial-gradient(circle at 86% -10%,rgba(73,132,240,.13),transparent 32%),linear-gradient(145deg,#fbfdff,#f3f6fb);overflow:hidden;box-shadow:0 22px 65px rgba(29,56,95,.09)}}
canvas{{display:block;width:100%;height:100%}}
.top{{position:absolute;left:26px;right:26px;top:21px;display:flex;align-items:flex-start;justify-content:space-between;gap:16px;pointer-events:none}}
.eyebrow{{font-size:10px;letter-spacing:.16em;color:#1769e0;font-weight:800}}.title{{margin-top:5px;color:#172033;font-size:16px;font-weight:760}}.sub{{margin-top:6px;color:#7b8798;font-size:10px}}
.meta{{display:flex;gap:7px;flex-wrap:wrap;justify-content:flex-end;max-width:52%}}.chip{{padding:6px 9px;border:1px solid #dfe5ee;border-radius:999px;background:rgba(255,255,255,.82);color:#687488;font-size:9px;backdrop-filter:blur(8px)}}
.bottom{{position:absolute;left:26px;right:26px;bottom:18px;display:grid;grid-template-columns:minmax(0,1.6fr) repeat(3,minmax(90px,.38fr));gap:9px;pointer-events:none}}
.story,.stat{{min-width:0;padding:9px 11px;border:1px solid #dfe5ec;border-radius:13px;background:rgba(255,255,255,.84)}}.story small,.stat small{{display:block;color:#929aa7;font-size:8px;letter-spacing:.05em}}.story b{{display:block;margin-top:4px;color:#445166;font-size:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.stat b{{display:block;margin-top:3px;color:#172033;font-size:13px}}
.boundary{{position:absolute;right:26px;bottom:80px;color:#8993a2;font-size:8px;pointer-events:none}}
@media(max-width:700px){{.top{{left:16px;right:16px;top:15px}}.meta{{display:none}}.bottom{{left:16px;right:16px;bottom:13px;grid-template-columns:1fr 1fr}}.story{{grid-column:1/-1}}.bottom .stat:last-child{{display:none}}.boundary{{display:none}}}}
</style></head><body><div class="shell">
<canvas id="replanCanvas" role="img" aria-label="Omni-180-v1 证据触发动态补证流程"></canvas>
<div class="top"><div><div class="eyebrow">EVIDENCE-TRIGGERED LEADER / CANVAS</div><div class="title">固定检查不是终点：中间证据决定下一步</div><div class="sub">Omni-180-v1 · 公开图像固定样本 pilot · 本地确定性运行</div></div><div class="meta"><span class="chip">固定工具 5</span><span class="chip">重规划 1</span><span class="chip">动态 Worker 3</span><span class="chip">结论 {safe_decision}</span></div></div>
<div class="bottom"><div class="story"><small>动态分支</small><b id="branchStory">等待证据波次</b></div><div class="stat"><small>固定分母</small><b id="sampleCount"></b></div><div class="stat"><small>Finding</small><b id="findingCount"></b></div><div class="stat"><small>整改工单</small><b id="workOrderCount"></b></div></div>
<div class="boundary">公开 pilot 不是客户现场、生产部署或全量数据认证</div>
</div><script>
const DATA={data};
document.getElementById('sampleCount').textContent=String(DATA.sampleCount);
document.getElementById('findingCount').textContent=String(DATA.findingCount);
document.getElementById('workOrderCount').textContent=String(DATA.workOrderCount);
const canvas=document.getElementById('replanCanvas'),ctx=canvas.getContext('2d');
const nodes=[
{{id:'intake',x:.075,y:.37,w:.12,h:.105,label:'批次进入',sub:'合同 · 权限'}},
{{id:'tools',x:.245,y:.37,w:.15,h:.105,label:'五类检查',sub:'质量 · 重复 · 标注'}},
{{id:'judge1',x:.43,y:.37,w:.13,h:.105,label:'首次裁决',sub:'形成中间证据'}},
{{id:'replan',x:.61,y:.37,w:.14,h:.105,label:'Leader 重规划',sub:'不是固定 DAG'}},
{{id:'conflict',x:.76,y:.22,w:.135,h:.09,label:'冲突复核',sub:'2 个样本'}},
{{id:'metadata',x:.76,y:.42,w:.135,h:.09,label:'元数据对账',sub:'漂移 15'}},
{{id:'resolution',x:.76,y:.62,w:.135,h:.09,label:'分组补证',sub:'28 组'}},
{{id:'judge2',x:.91,y:.42,w:.115,h:.105,label:'复判',sub:'RECAPTURE'}},
{{id:'orders',x:.91,y:.67,w:.115,h:.095,label:'证据交付',sub:'45 工单'}}
];
const edges=[['intake','tools'],['tools','judge1'],['judge1','replan'],['replan','conflict'],['replan','metadata'],['replan','resolution'],['conflict','judge2'],['metadata','judge2'],['resolution','judge2'],['judge2','orders']];
let W=0,H=0,dpr=1,hover=null;
function resize(){{const r=canvas.getBoundingClientRect();dpr=Math.min(devicePixelRatio||1,2);W=r.width;H=r.height;canvas.width=W*dpr;canvas.height=H*dpr;ctx.setTransform(dpr,0,0,dpr,0,0)}}
function geom(n){{return{{x:(n.x-n.w/2)*W,y:(n.y-n.h/2)*H,w:n.w*W,h:n.h*H}}}}
function round(x,y,w,h,r){{ctx.beginPath();ctx.roundRect(x,y,w,h,r)}}
function center(id){{const g=geom(nodes.find(v=>v.id===id));return{{x:g.x+g.w/2,y:g.y+g.h/2}}}}
function curve(a,b){{const p=center(a),q=center(b),dx=q.x-p.x;return{{p,q,c1:{{x:p.x+dx*.48,y:p.y}},c2:{{x:q.x-dx*.48,y:q.y}}}}}}
function bx(s,t){{const u=1-t;return u*u*u*s.p.x+3*u*u*t*s.c1.x+3*u*t*t*s.c2.x+t*t*t*s.q.x}}
function by(s,t){{const u=1-t;return u*u*u*s.p.y+3*u*u*t*s.c1.y+3*u*t*t*s.c2.y+t*t*t*s.q.y}}
function drawEdge(a,b,time,index){{const s=curve(a,b);ctx.beginPath();ctx.moveTo(s.p.x,s.p.y);ctx.bezierCurveTo(s.c1.x,s.c1.y,s.c2.x,s.c2.y,s.q.x,s.q.y);ctx.strokeStyle=(a==='replan'||b==='judge2')?'#b9ccef':'#d5dce7';ctx.lineWidth=(a==='replan'||b==='judge2')?1.6:1.2;ctx.stroke();const t=((time*.00013)+(index*.09))%1;ctx.beginPath();ctx.arc(bx(s,t),by(s,t),2.4,0,Math.PI*2);ctx.fillStyle=(a==='replan')?'#1769e0':(b==='orders'?'#c17a0c':'#4f80d8');ctx.fill()}}
function drawNode(n){{const g=geom(n),dynamic=['conflict','metadata','resolution'].includes(n.id),active=hover===n.id;ctx.save();ctx.shadowColor=dynamic?'rgba(23,105,224,.14)':'rgba(29,50,80,.07)';ctx.shadowBlur=active?18:10;ctx.shadowOffsetY=4;round(g.x,g.y,g.w,g.h,14);ctx.fillStyle=dynamic?'#eef5ff':'rgba(255,255,255,.96)';ctx.fill();ctx.shadowBlur=0;ctx.strokeStyle=active?'#1769e0':(dynamic?'#b7cff5':'#dfe4eb');ctx.lineWidth=active?1.8:1;ctx.stroke();ctx.fillStyle=n.id==='orders'?'#c17a0c':(dynamic?'#1769e0':'#64748b');round(g.x+9,g.y+10,4,Math.max(16,g.h-20),3);ctx.fill();ctx.fillStyle='#192235';ctx.font='700 11px "Microsoft YaHei",system-ui';ctx.fillText(n.label,g.x+22,g.y+23);ctx.fillStyle='#7b8797';ctx.font='9px "Microsoft YaHei",system-ui';ctx.fillText(n.sub,g.x+22,g.y+39);ctx.restore()}}
function frame(time){{ctx.clearRect(0,0,W,H);edges.forEach((e,i)=>drawEdge(e[0],e[1],time,i));nodes.forEach(drawNode);const index=Math.floor(time/2600)%Math.max(DATA.tasks.length,1),task=DATA.tasks[index];if(task)document.getElementById('branchStory').textContent=task.label+'：'+task.effect;requestAnimationFrame(frame)}}
canvas.addEventListener('mousemove',e=>{{const r=canvas.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top;hover=null;for(const n of nodes){{const g=geom(n);if(x>=g.x&&x<=g.x+g.w&&y>=g.y&&y<=g.y+g.h)hover=n.id}}canvas.style.cursor=hover?'pointer':'default'}});
window.addEventListener('resize',resize);resize();requestAnimationFrame(frame);
</script></body></html>"""


__all__ = ["build_reviewer_canvas"]
