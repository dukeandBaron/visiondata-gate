import { ClipboardList, ArrowUpRight, X } from "lucide-react";
import { businessTaskUrl, findBusinessTask } from "../businessTasks";
import "../styles/commercial-workflow.css";

interface Props {
  purpose: string | null;
  surface: "workbook" | "task";
  onNavigate: (href: string) => void;
  onClear: () => void;
}

export function BusinessTaskContext({ purpose, surface, onNavigate, onClear }: Props) {
  if (purpose === null) return null;
  const task = findBusinessTask(purpose);
  return <section className={`business-task-context${task ? "" : " is-unknown"}`} aria-label="当前业务操作指引">
    <div className="business-task-context__row">
      <ClipboardList size={17} aria-hidden="true" />
      <div><small>页面工作目标 · 非运行合同</small><strong>{task?.title ?? "链接中的业务任务不存在"}</strong></div>
      <button type="button" onClick={() => onNavigate(task ? businessTaskUrl(task.id, "/start") : "/start")}>{task ? "操作指引" : "重新选择工作"}<ArrowUpRight size={14} /></button>
      <button type="button" onClick={onClear} aria-label="收起业务指引" title="只移除页面指引，不改变数据或任务"><X size={15} /></button>
    </div>
    {task ? <details><summary>本次交付要求与下一步</summary><div>
      <p><strong>预期交付：</strong>{task.outcome}</p>
      <p>{surface === "workbook" ? "完成图片与标注复核后，可通过上方「冻结项目并交给 Agent」封存输入，再在任务工作台确认并运行。导入图片本身不会运行 Agent。" : "此目标来自页面导航，不代表当前选中任务已绑定该业务目的。请核对当前任务的来源与实际合同，并按预检和人工审批状态继续。"}</p>
      {task.id === "annotation-rework" ? <p>框的语义正确性由复核人判断。像素工单关闭不触发批次复验；保存修订后需重新冻结项目并检查。</p> : null}
      {task.id === "dataset-reuse" ? <p>冻结会纳入当前项目的全部资产。若要单独检查第二批，请先新建独立项目；追加到旧项目得到的是累计项目快照。重新核对实际合同内容与摘要，不能仅凭相同软件版本视为同合同。</p> : null}
      <p className="business-task-context__boundary">选择业务目标不修改后台用途、数据划分或验收权限。技术检查、客户接受和生产批准是不同状态。</p>
    </div></details> : <p role="alert">请重新选择或收起指引。现有数据、检查结果与任务权限未改变。</p>}
  </section>;
}
