import { Download, FileUp, ArrowRight } from "lucide-react";
import { useEffect, useState, type FormEvent, type ChangeEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { businessTasks, businessTaskUrl, findBusinessTask, type BusinessTaskId } from "../businessTasks";
import { buildPilotPlan, emptyPilotDraft, parsePilotPlan, pilotFields, pilotMetrics, type PilotDraft, type PilotMetricId } from "../commercialPilot";
import "../styles/commercial-workflow.css";

export function PilotPlanPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const purpose = searchParams.get("purpose");
  const requestedTask = findBusinessTask(purpose);
  const [draft, setDraft] = useState<PilotDraft>(emptyPilotDraft);
  const [feedback, setFeedback] = useState("");
  const [error, setError] = useState("");
  const [reading, setReading] = useState(false);
  const task = findBusinessTask(draft.businessTaskId)!;

  useEffect(() => {
    if (requestedTask) setDraft((current) => ({ ...current, businessTaskId: requestedTask.id }));
  }, [requestedTask]);

  function selectTask(id: BusinessTaskId) {
    setDraft((current) => ({ ...current, businessTaskId: id }));
    setSearchParams({ purpose: id }, { replace: true });
    setFeedback(""); setError("");
  }

  function update(key: keyof PilotDraft, value: string | PilotMetricId[]) {
    setDraft((current) => ({ ...current, [key]: value }));
    setFeedback(""); setError("");
  }
  function exportDraft(event: FormEvent) {
    event.preventDefault(); setError(""); setFeedback("");
    try {
      const plan = buildPilotPlan(draft);
      const url = URL.createObjectURL(new Blob([JSON.stringify(plan, null, 2)], { type: "application/json" }));
      const anchor = document.createElement("a");
      anchor.href = url; anchor.download = "industrial-pilot-plan.draft.json";
      document.body.append(anchor); anchor.click(); anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setFeedback("已生成范围书草稿并触发下载。它不构成客户批准或实测效果；离开页面前请保留下载文件。");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "无法导出范围书。"); }
  }
  async function importDraft(event: ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0]; event.currentTarget.value = "";
    if (!file) return;
    setReading(true); setError(""); setFeedback("");
    try {
      if (file.size > 50000) throw new Error("仅支持 50 KB 以内的试点范围书。");
      const text = await file.text();
      const imported = parsePilotPlan(text);
      setDraft(imported);
      setSearchParams({ purpose: imported.businessTaskId }, { replace: true });
      const legacy = JSON.parse(text).schema_version === "industrial-delivery.pilot-plan.v1";
      setFeedback(`${legacy ? "旧版 v1 草稿已按「交付前检查一批数据」读入，再导出将使用 v2。" : "已读入本地范围书草稿。"}未提交到服务器，未导入测量或授权结果。`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "无法读取范围书。"); }
    finally { setReading(false); }
  }

  return (
    <div className="pilot-plan-page">
      <header><span>客户试点 · 范围与验收条件</span><h1>先约定一项可以验收的交付</h1><p>先选工作任务，再填写真实问题、使用者、数据范围与对照方法。客户接受、数据技术检查和生产放行分别确认。</p></header>
      <div className="pilot-plan-notice"><strong>本地草稿 · 尚未批准</strong><p>内容仅保留在当前页面，离开或刷新会丢失。可导出后重新导入继续编辑。本页面不上传资料、不保存正式审批，也不生成客户效果数据。</p></div>
      <form onSubmit={exportDraft}>
        {purpose && !requestedTask ? <p className="pilot-plan-error" role="alert">链接中的业务任务不存在。请先选择任务，再填写或导出；不会创建后台任务。</p> : null}
        <fieldset className="business-task-picker"><legend>这次要验证哪项工作？</legend><div>
          {businessTasks.map((item) => <button key={item.id} type="button" disabled={reading} aria-pressed={draft.businessTaskId === item.id && (!purpose || Boolean(requestedTask))} onClick={() => selectTask(item.id)}><small>{item.tag}</small><strong>{item.title}</strong></button>)}
        </div><p>切换任务会调整拟交付物，保留你已填写的内容和所选指标，请自行核对是否仍适用。</p></fieldset>
        <div className="pilot-plan-form">
          {pilotFields.map((field) => <label key={field.key} className={field.max > 240 ? "is-wide" : ""}><span>{field.label} *</span>{field.max > 240 ? <textarea required maxLength={field.max} value={draft[field.key]} placeholder={field.placeholder} onChange={(e) => update(field.key, e.target.value)} rows={3} /> : <input required maxLength={field.max} value={draft[field.key]} placeholder={field.placeholder} onChange={(e) => update(field.key, e.target.value)} />}</label>)}
        </div>
        <fieldset className="pilot-plan-metrics"><legend>选择要验证的变化</legend><p>每项指标在范围书中均为“未测量”。试点前后必须采用相同定义，并记录来源与独立复核方法。</p>
          {pilotMetrics.map((metric) => <label key={metric.id}><input type="checkbox" checked={draft.metricIds.includes(metric.id)} onChange={(e) => update("metricIds", e.target.checked ? [...draft.metricIds, metric.id] : draft.metricIds.filter((id) => id !== metric.id))} /><div><strong>{metric.name}<em>{metric.tier}</em></strong><small>{metric.unit}</small><p>{metric.definition}</p><span>需要的证据：{metric.evidence}</span></div></label>)}
        </fieldset>
        <section className="pilot-plan-deliverables"><h2>本次拟交付 · {task.title}</h2><ul>{task.steps.map((step) => <li key={step.title}>{step.output}</li>)}</ul><p>{task.outcome}</p><details><summary>本任务当前的能力边界</summary><ul>{task.limitations.map((limit) => <li key={limit}>{limit}</li>)}</ul></details><p>安装适配、模型训练和产线工艺优化如有需求，另行约定范围与验收；本范围书不代表这些服务已经提供。</p></section>
        {error ? <p className="pilot-plan-error" role="alert">{error}</p> : null}
        {feedback ? <p className="pilot-plan-feedback" role="status">{feedback}</p> : null}
        <div className="pilot-plan-actions"><button type="submit" disabled={reading || Boolean(purpose && !requestedTask)}><Download size={16} /> 导出试点范围书</button><label className="pilot-plan-import"><FileUp size={16} />{reading ? "正在读取" : "读入已有草稿"}<input type="file" accept="application/json,.json" disabled={reading} onChange={(e) => void importDraft(e)} /></label><Link to={businessTaskUrl(task.id, "/start")}>查看本任务操作指引<ArrowRight size={16} /></Link></div>
      </form>
    </div>
  );
}
