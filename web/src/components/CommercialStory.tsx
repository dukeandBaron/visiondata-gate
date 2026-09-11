import { ArrowRight, ClipboardList, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { businessTasks, businessTaskUrl, findBusinessTask, type BusinessTaskId } from "../businessTasks";
import "../styles/commercial-workflow.css";

export function CommercialStory({ publicMode = false }: { publicMode?: boolean }) {
  const [taskId, setTaskId] = useState<BusinessTaskId>("dataset-acceptance");
  const [selected, setSelected] = useState(0);
  const task = findBusinessTask(taskId)!;
  const stage = task.steps[selected] ?? task.steps[0]!;
  const route = stage.href === "/pilot" || stage.href === "/workspace" ? businessTaskUrl(task.id, stage.href) : stage.href;
  return (
    <section className="commercial-story" id="business-story" aria-labelledby="commercial-story-title">
      <header className="commercial-story__heading">
        <div><span>面向视觉数据交付 · 待客户试点验证</span><h2 id="commercial-story-title">从收到一批数据，到交出一份依据</h2></div>
        <Link to={businessTaskUrl(task.id, "/start")}><ClipboardList size={16} /> 查看本任务指引</Link>
      </header>
      <p className="commercial-story__lead">新采集的一批图、外包交回的标注、换型后的修订数据，都需要有人检查和交接。先做好一项工作，再验证下一批能否沿用。以下是产品应用说明，不是已落地客户的效果案例。</p>
      <div className="business-task-picker" role="group" aria-label="选择应用任务"><div>{businessTasks.map((item) => <button key={item.id} type="button" aria-pressed={taskId === item.id} onClick={() => { setTaskId(item.id); setSelected(0); }}><small>{item.tag}</small><strong>{item.title}</strong></button>)}</div></div>
      <div className="commercial-story__roles">
        <span><small>优先买方</small>{task.buyer}</span>
        <span><small>实际使用</small>{task.user}</span>
        <span><small>本次交付</small>{task.outcome}</span>
      </div>
      <div className="commercial-story__journey">
        <div className="commercial-story__steps" role="group" aria-label="选择交付流程阶段">
          {task.steps.map((item, index) => <button key={item.title} type="button" aria-pressed={selected === index} onClick={() => setSelected(index)}><span>{index + 1}</span><div><strong>{item.title}</strong><small>{item.person}</small></div><ArrowRight size={15} /></button>)}
        </div>
        <article className="commercial-story__detail" aria-live="polite">
          <small>{stage.person} · 下一步工作</small><h3>{stage.title}</h3><p>{stage.detail}</p>
          <div><small>这一步交付什么</small><strong>{stage.output}</strong></div>
          <Link to={route}>{publicMode && stage.href !== "/pilot" ? `${stage.action}（公开体验）` : stage.action}<ArrowRight size={15} /></Link>
        </article>
      </div>
      <footer className="commercial-story__boundary"><ShieldCheck size={17} /><p>先验证用户能否独立完成、每批实际工作时长和第二项目接入成本。几何检查不替代标注语义复核，数据检查通过不等于客户接受或生产放行。{publicMode ? "公开体验不代表客户或工厂在线接入。" : "业务指标以实际试点记录为准。"}</p></footer>
    </section>
  );
}
