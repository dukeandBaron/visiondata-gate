import { ArrowRight, ClipboardCheck, ScanLine, Layers, ShieldCheck } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { businessTasks, businessTaskUrl, findBusinessTask, scoringCriteria } from "../businessTasks";
import { publicReplayMode } from "../publicReplay";
import "../styles/commercial-workflow.css";

const taskIcons = { "dataset-acceptance": ClipboardCheck, "annotation-rework": ScanLine, "dataset-reuse": Layers };

export function TaskGuidePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const purpose = searchParams.get("purpose");
  const task = findBusinessTask(purpose ?? "dataset-acceptance");
  function stepHref(href: string) {
    if (!task) return "/start";
    return href === "/pilot" || href === "/workspace" ? businessTaskUrl(task.id, href) : href;
  }

  return <div className="task-guide-page">
    <header className="task-guide-heading"><span>从一项工作开始</span><h1>这批数据，下一步需要做什么？</h1><p>选择要交付的结果，明确输入与负责人，再进入已有工作模块。这里是操作指引，不是任务运行进度。</p></header>
    <div className="business-task-picker" role="group" aria-label="选择业务任务"><div>
      {businessTasks.map((item) => { const Icon = taskIcons[item.id]; return <button key={item.id} type="button" aria-pressed={task?.id === item.id} onClick={() => setSearchParams({ purpose: item.id })}><Icon size={21} /><small>{item.tag}</small><strong>{item.title}</strong></button>; })}
    </div></div>
    {!task ? <section className="task-guide-unknown" role="alert"><h2>未找到这个业务任务</h2><p>请选择上方的一项工作。未知链接不会套用默认任务，也不会创建或批准后台工作。</p></section> : <>
      <section className="task-guide-brief" aria-live="polite"><div><span className="task-guide-label">工作目标</span><h2>{task.title}</h2><p>{task.trigger}</p><dl><dt>优先买方</dt><dd>{task.buyer}</dd><dt>实际操作者</dt><dd>{task.user}</dd><dt>预期交付</dt><dd>{task.outcome}</dd></dl></div><aside><h3>开始前需要</h3><ul>{task.inputs.map((input) => <li key={input}>{input}</li>)}</ul><Link className="task-guide-primary" to={businessTaskUrl(task.id, "/workspace")}>{publicReplayMode ? "打开公开体验工作簿" : "进入工作簿开始处理"}<ArrowRight size={16} /></Link><Link to={businessTaskUrl(task.id, "/pilot")}>为这项工作约定试点条件 <ArrowRight size={15} /></Link></aside></section>
      <ol className="task-guide-flow" aria-label="任务操作指引">{task.steps.map((step, index) => <li key={step.title}><span className="task-guide-flow__number">{index + 1}</span><div><small>{step.person}</small><h3>{step.title}</h3><p>{step.detail}</p><span className="task-guide-output">交付物 · {step.output}</span></div><Link to={stepHref(step.href)}>{step.action}{publicReplayMode && step.href !== "/pilot" ? "（体验）" : ""}<ArrowRight size={15} /></Link></li>)}</ol>
      <section className="task-guide-safety"><ShieldCheck size={20} /><div><h2>运行范围与人工责任</h2><p>{publicReplayMode ? "当前为公开体验：公开浏览与冻结回放不等于本地后端工单、客户验收或真实工厂连接。实际持久化流程需在本地部署中使用。" : "本地 API 连接只代表本机服务可用，不表示真实工厂已接入。请先选对工作空间与项目；页面跳转不会上传数据、批准整改或生成结果。"}</p><ul>{task.limitations.map((limit) => <li key={limit}>{limit}</li>)}</ul></div></section>
      <details className="task-guide-proof"><summary>评审与试点：这项工作如何证明价值？</summary><p>以下按通用 / 复赛六维标准组织证据，并非得分预测；决赛权重及要求以最新官方通知为准。</p><div className="task-guide-proof__scroll"><table><thead><tr><th scope="col">评审维度</th><th scope="col">要回答的问题</th><th scope="col">本任务需要的证明</th></tr></thead><tbody>{scoringCriteria.map((criterion) => <tr key={criterion.id}><th scope="row">{criterion.name}<small>{criterion.weight}</small></th><td>{criterion.question}</td><td>{task.proof[criterion.id]}</td></tr>)}</tbody></table></div><p>目前没有客户独立使用、付费验收与跨项目效果数据。应先记录独立完成率、人工有效工作时长和第二项目接入成本；不能把数据检查通过写成产线良品率提升。</p></details>
    </>}
  </div>;
}
